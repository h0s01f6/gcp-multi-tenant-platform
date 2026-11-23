"""Tenant registry validator (schema v2.1).

Usage:  python3 -m tools.registry.validate [registry_root]      (default: registry/)
Exit code 0 = valid, 1 = findings. Every finding carries a rule ID (R01-R16) – see registry/README.md.
"""
import json
import pathlib
import re
import sys
from dataclasses import dataclass

import jsonschema

from .loader import DuplicateKeyError, load_yaml
from .naming import ENVS, derived_names, validate_names

RESERVED_CONFIG_KEYS = {"hostname", "host", "domain", "bucket", "database", "namespace",
                        "project", "service_account", "sa", "secret", "pool", "cluster"}


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    message: str

    def __str__(self):
        return f"ERROR {self.rule} {self.path}: {self.message}"


@dataclass
class Registry:
    root: pathlib.Path
    inventory: dict
    products: dict      # slug -> (path, data)
    tenants: dict       # slug -> (path, data)


def _semver(v):
    return tuple(int(x) for x in v.split("."))


def _version_supported(version, patterns):
    for p in patterns:
        if re.fullmatch(re.escape(p).replace(r"x", r"[0-9]+"), version):
            return True
    return False


def _load_dir(directory, schema, kind, findings):
    validator = jsonschema.Draft202012Validator(schema)
    items, by_slug = {}, {}
    for path in sorted(directory.glob("*.yaml")):
        rel = str(path)
        try:
            data = load_yaml(path)
        except DuplicateKeyError as exc:
            findings.append(Finding("R01", rel, f"{exc} – duplicate entries are not allowed"))
            continue
        except Exception as exc:  # malformed YAML
            findings.append(Finding("R01", rel, f"cannot parse YAML: {exc}"))
            continue
        errs = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
        for e in errs:
            loc = "/".join(str(p) for p in e.path) or "(root)"
            findings.append(Finding("R02", rel, f"schema: {loc}: {e.message}"))
        if errs:
            continue
        slug = data[kind]
        if path.stem != slug:
            findings.append(Finding("R03", rel, f"file name '{path.name}' must be '{slug}.yaml'"))
        if slug in by_slug:
            findings.append(Finding("R04", rel, f"{kind} '{slug}' is also defined in {by_slug[slug]}"))
            continue
        by_slug[slug] = rel
        items[slug] = (rel, data)
    return items


def load_registry(root):
    root = pathlib.Path(root)
    findings = []
    inventory = load_yaml(root / "platform" / "inventory.yaml")
    tschema = json.loads((root / "schemas" / "tenant.schema.json").read_text())
    pschema = json.loads((root / "schemas" / "product.schema.json").read_text())
    products = _load_dir(root / "products", pschema, "product", findings)
    tenants = _load_dir(root / "tenants", tschema, "tenant", findings)
    return Registry(root, inventory, products, tenants), findings


def _check_products(reg, findings):
    groups = reg.inventory.get("product_groups", {})
    for slug, (path, p) in reg.products.items():
        for e in validate_names("abc", slug, "prd"):          # product-side length budget (K18)
            if "product slug" in e or "service-account" in e or "MySQL" in e:
                findings.append(Finding("R11", path, f"product slug too long for derived names: {e}"))
                break
        db = p.get("database")
        if db:
            g = db["pool_group"]
            if g not in groups:
                findings.append(Finding("R15", path, f"pool_group '{g}' not in inventory product_groups"))
            elif slug not in groups[g]:
                findings.append(Finding("R15", path, f"product not listed in inventory group '{g}'"))
        for cohort, version in (p.get("cohorts") or {}).items():
            if not _version_supported(version, p["supported_versions"]):
                findings.append(Finding("R08", path, f"cohort {cohort} version {version} not in supported_versions"))
        if p.get("version") and not _version_supported(p["version"], p["supported_versions"]):
            findings.append(Finding("R08", path, f"version {p['version']} not in supported_versions"))


def _check_placement(reg, path, tenant, t, product, p, envs_deployed, sub, findings):
    cells, pools = reg.inventory.get("gke_cells", {}), reg.inventory.get("sql_pools", {})
    placement = sub.get("placement", {})
    for env in placement:
        if env not in envs_deployed:
            findings.append(Finding("R10", path, f"{product}: placement for '{env}' but nothing is deployed there"))
    for env in envs_deployed:
        where = f"{product}/{env}"
        pl = placement.get(env)
        if pl is None:
            findings.append(Finding("R10", path, f"{where}: missing placement"))
            continue
        if p["runtime"] == "gke":
            cell = pl.get("gke")
            if not cell:
                findings.append(Finding("R10", path, f"{where}: GKE product needs a 'gke' cell"))
            elif cell not in cells:
                findings.append(Finding("R10", path, f"{where}: unknown GKE cell '{cell}'"))
            elif cells[cell]["env"] != env:
                findings.append(Finding("R10", path, f"{where}: cell '{cell}' serves '{cells[cell]['env']}', not '{env}'"))
        elif "gke" in pl:
            findings.append(Finding("R10", path, f"{where}: '{p['runtime']}' product must not have a 'gke' placement"))
        db = p.get("database")
        pool_name = pl.get("sql")
        if db and not pool_name:
            findings.append(Finding("R10", path, f"{where}: product needs a database but has no 'sql' pool"))
        if not db and pool_name:
            findings.append(Finding("R10", path, f"{where}: product has no database; remove 'sql'"))
        if not (db and pool_name):
            continue
        pool = pools.get(pool_name)
        if pool is None:
            findings.append(Finding("R10", path, f"{where}: unknown SQL pool '{pool_name}'"))
            continue
        if pool["env"] != env:
            findings.append(Finding("R10", path, f"{where}: pool '{pool_name}' serves '{pool['env']}', not '{env}'"))
        if pool["mysql"] != db["major_version"]:
            findings.append(Finding("R10", path, f"{where}: pool MySQL {pool['mysql']} != product {db['major_version']}"))
        if env == "prd":
            dedicated_for = pool.get("dedicated_tenant")
            if t["isolation_tier"] in ("enhanced", "dedicated"):
                if dedicated_for != tenant:
                    findings.append(Finding("R16", path, f"{where}: {t['isolation_tier']} tenant needs its own instance (pool with dedicated_tenant: {tenant})"))
            else:
                if dedicated_for:
                    findings.append(Finding("R16", path, f"{where}: pool '{pool_name}' is dedicated to '{dedicated_for}'"))
                elif pool.get("pool_group") != db["pool_group"]:
                    findings.append(Finding("R10", path, f"{where}: pool group '{pool.get('pool_group')}' != product group '{db['pool_group']}'"))
                elif pool.get("products") and product not in pool["products"]:
                    findings.append(Finding("R10", path, f"{where}: pool '{pool_name}' is split for {pool['products']}, not '{product}'"))


def product_pool_for(inventory, product, env):
    """Registered product-owned pool for a Shared/Cohort product in one environment (or None)."""
    matches = sorted(n for n, v in (inventory.get("product_sql_pools") or {}).items()
                     if v.get("owner_product") == product and v.get("env") == env)
    return matches[0] if matches else None


def _check_product_pools(reg, findings):
    """R17 – product-owned pools: well-formed, and present for every environment a Shared/Cohort product is deployed in."""
    inv_path = str(reg.root / "platform" / "inventory.yaml")
    for name, v in sorted((reg.inventory.get("product_sql_pools") or {}).items()):
        prod, env = v.get("owner_product"), v.get("env")
        if not re.fullmatch(r"psql-[a-z][a-z0-9]{1,10}-(dev|stg|uat|prd)-[0-9]{2}", name):
            findings.append(Finding("R17", inv_path, f"product pool name '{name}' must be psql-<product>-<env>-NN"))
        if prod not in reg.products:
            findings.append(Finding("R17", inv_path, f"{name}: owner_product '{prod}' not in catalogue"))
            continue
        p = reg.products[prod][1]
        if p["deployment_model"] == "dedicated":
            findings.append(Finding("R17", inv_path, f"{name}: owner '{prod}' is Dedicated – product pools are for Shared/Cohort only"))
        if not name.startswith(f"psql-{prod}-{env}-"):
            findings.append(Finding("R17", inv_path, f"{name}: name does not match owner_product/env ({prod}/{env})"))
        tier = "prd" if env == "prd" else "nonprd"
        if v.get("project") != f"p-{prod}-{tier}":
            findings.append(Finding("R17", inv_path, f"{name}: project must be p-{prod}-{tier}, not '{v.get('project')}'"))
        db = p.get("database")
        if db and v.get("mysql") != db["major_version"]:
            findings.append(Finding("R17", inv_path, f"{name}: MySQL {v.get('mysql')} != product {db['major_version']}"))
    needed = set()
    for _, (path, t) in reg.tenants.items():
        for product, sub in t["subscriptions"].items():
            p = reg.products.get(product, (None, None))[1]
            if not p or not p.get("database") or p["deployment_model"] == "dedicated":
                continue
            envs = ENVS if p["deployment_model"] == "shared" else tuple(sub.get("cohort", {}))
            needed.update((product, e, path) for e in envs)
    reported = set()
    for product, env, path in sorted(needed):
        if (product, env) not in reported and not product_pool_for(reg.inventory, product, env):
            findings.append(Finding("R17", path, f"{product}/{env}: no registered product-owned pool in inventory product_sql_pools"))
            reported.add((product, env))


def _check_tenants(reg, findings):
    deployments = {}          # (tenant, product, env) -> path
    derived_owner = {}        # derived name -> (tenant, product)
    for tenant, (path, t) in reg.tenants.items():
        if t["owners"]["technical"] != f"grp-hum-cust-{tenant}-support":
            findings.append(Finding("R14", path, f"owners.technical must be grp-hum-cust-{tenant}-support"))
        for product, sub in t["subscriptions"].items():
            if product not in reg.products:
                findings.append(Finding("R05", path, f"unknown product '{product}'"))
                continue
            _, p = reg.products[product]
            model = p["deployment_model"]
            for key in RESERVED_CONFIG_KEYS & set((sub.get("config") or {}).keys()):
                findings.append(Finding("R13", path, f"{product}: config key '{key}' is reserved – resource names are derived, not declared"))
            if model == "dedicated":
                if "cohort" in sub or "versions" not in sub:
                    findings.append(Finding("R06", path, f"{product}: dedicated product needs 'versions' and no 'cohort'"))
                    continue
                per_env = sub["versions"]
            elif model == "shared":
                if {"versions", "cohort", "placement"} & set(sub):
                    findings.append(Finding("R06", path, f"{product}: shared product takes only 'config' (version is set in the catalogue)"))
                continue
            else:  # cohort
                if "versions" in sub or "placement" in sub or "cohort" not in sub:
                    findings.append(Finding("R06", path, f"{product}: cohort product needs 'cohort' only"))
                    continue
                per_env = sub["cohort"]
                for env, c in per_env.items():
                    if c not in p["cohorts"]:
                        findings.append(Finding("R06", path, f"{product}/{env}: unknown cohort '{c}'"))
            envs = [e for e in ENVS if e in per_env]
            expected = list(ENVS[:len(envs)])
            if envs != expected:
                findings.append(Finding("R07", path, f"{product}: environments {envs} break the promotion chain – must be a prefix of {list(ENVS)}"))
            if model == "dedicated":
                for env, v in per_env.items():
                    if not _version_supported(v, p["supported_versions"]):
                        findings.append(Finding("R08", path, f"{product}/{env}: version {v} not in supported_versions {p['supported_versions']}"))
                    if v in p.get("blocked_versions", []):
                        findings.append(Finding("R08", path, f"{product}/{env}: version {v} is blocked"))
                if "prd" in per_env and "uat" in per_env and _semver(per_env["prd"]) > _semver(per_env["uat"]):
                    findings.append(Finding("R09", path, f"{product}: prd {per_env['prd']} is newer than uat {per_env['uat']}"))
                _check_placement(reg, path, tenant, t, product, p, envs, sub, findings)
            for env in envs:
                for e in validate_names(tenant, product, env):
                    findings.append(Finding("R11", path, f"{product}/{env}: {e}"))
                key = (tenant, product, env)
                if key in deployments:
                    findings.append(Finding("R12", path, f"duplicate deployment {key} (also in {deployments[key]})"))
                deployments[key] = path
                names = derived_names(tenant, product, env)
                for name in names["sa_ids"] + [names["database"] + "@" + env]:
                    owner = derived_owner.setdefault(name, (tenant, product))
                    if owner != (tenant, product):
                        findings.append(Finding("R12", path, f"derived name '{name}' collides with {owner}"))
    return deployments


def validate(root="registry"):
    reg, findings = load_registry(root)
    _check_products(reg, findings)
    _check_tenants(reg, findings)
    _check_product_pools(reg, findings)
    return reg, findings


def main(argv):
    root = argv[1] if len(argv) > 1 else "registry"
    reg, findings = validate(root)
    for f in findings:
        print(f)
    subs = sum(len(t["subscriptions"]) for _, t in reg.tenants.values())
    print(f"\n{len(reg.tenants)} tenants, {len(reg.products)} products, {subs} subscriptions, "
          f"{len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
