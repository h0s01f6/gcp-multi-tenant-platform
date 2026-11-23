"""D2 – derive the identity plan from the tenant registry.

Usage:  python3 -m tools.identity.derive [registry_root] [-o build/identity-plan.json]

The plan is declarative: removing a subscription from the registry removes its entries from the plan,
and Terraform (Stage 5) destroys what is no longer present. Output is deterministic (sorted keys).
Status: implemented + locally tested; not applied to any GCP project.
"""
import argparse
import json
import pathlib
import re
import sys

from tools.registry.naming import ENVS, env_tier, tenant_sa_id
from tools.registry.validate import product_pool_for, validate

SA_DOMAIN = "iam.gserviceaccount.com"
PLAN_SCHEMA_VERSION = "1.0"


def sa_email(account_id, project):
    # Logical project name; Stage 5 maps logical names to real project IDs (which carry a random suffix).
    return f"{account_id}@{project}.{SA_DOMAIN}"


def sqlconn_group(pool_project):
    m = re.fullmatch(r"plt-sql-(prd|nonprd)-(\d{2})", pool_project)
    return f"grp-wl-sqlconn-{m.group(1)}-{m.group(2)}" if m else None


class Plan:
    def __init__(self):
        self.sections = {k: {} for k in (
            "service_accounts", "workload_identity_bindings", "kubernetes_namespaces",
            "cloud_sql_databases", "cloud_sql_iam_users", "group_memberships",
            "project_iam", "resource_iam")}

    def add(self, section, key, value):
        existing = self.sections[section].get(key)
        if existing is not None and existing != value:
            raise ValueError(f"conflicting plan entry {section}/{key}")
        self.sections[section][key] = value

    def to_dict(self):
        return {"schema_version": PLAN_SCHEMA_VERSION,
                **{k: dict(sorted(v.items())) for k, v in self.sections.items()}}


def _add_sa(plan, *, account_id, project, tenant, product, env, purpose, model, runtime, tenants=None):
    if not (6 <= len(account_id) <= 30):
        raise ValueError(f"service-account ID '{account_id}' outside 6-30 chars")
    email = sa_email(account_id, project)
    plan.add("service_accounts", f"{project}/{account_id}", {
        "project": project, "account_id": account_id, "email": email,
        "display_name": f"{tenant or 'shared'} {product} {env} {purpose}".strip(),
        "tenant": tenant, "product": product, "env": env, "env_tier": env_tier(env),
        "purpose": purpose, "deployment_model": model, "runtime": runtime,
        # Explicit isolation boundary (ADR-006 rev. 3): a Dedicated identity serves exactly one tenant, so
        # the database grant is the tenant boundary. A Shared/Cohort identity serves several tenants, so the
        # tenant boundary for data access is the APPLICATION, not IAM or MySQL.
        "tenant_scope": "single" if tenant else "multi",
        "isolation_boundary": "identity-and-database" if tenant else "application",
        "served_tenants": [tenant] if tenant else sorted(tenants or []),
        "labels": {"tenant": tenant or "multi", "product": product, "env": env,
                   "env_tier": env_tier(env), "deployment_model": model}})
    return email


def _db_identities(plan, *, pool, pool_project, databases, env, entries, connect_group, connect_project,
                   isolation_boundary="identity-and-database"):
    """entries: list of (purpose, account_id, email). Adds SQL users + connect permission."""
    for purpose, account_id, email in entries:
        plan.add("cloud_sql_iam_users", f"{pool}/{account_id}", {
            "pool": pool, "pool_project": pool_project, "user": account_id, "sa_email": email,
            "type": "CLOUD_IAM_SERVICE_ACCOUNT", "databases": sorted(databases), "purpose": purpose, "env": env,
            "isolation_boundary": isolation_boundary})
        if connect_group:          # mechanism 1: group in the pool project's IAM policy (ADR-009 rev. 2, T-G2)
            plan.add("group_memberships", f"{connect_group}/{email}", {
                "group": connect_group, "member": email, "member_type": "SERVICE_ACCOUNT",
                "grants_via_group": ["roles/cloudsql.client", "roles/cloudsql.instanceUser"],
                "scope_project": pool_project})
        else:                      # dedicated instance in a tenant / product project: individual binding
            for role in ("roles/cloudsql.client", "roles/cloudsql.instanceUser"):
                plan.add("project_iam", f"{connect_project}/{role}/{email}", {
                    "project": connect_project, "role": role, "member": f"serviceAccount:{email}"})


def _gke(plan, *, cell, cell_project, namespace, labels, bindings):
    plan.add("kubernetes_namespaces", f"{cell}/{namespace}", {
        "cluster": cell, "cluster_project": cell_project, "namespace": namespace, "labels": labels})
    for ksa, email in bindings:
        plan.add("workload_identity_bindings", f"{cell}/{namespace}/{ksa}", {
            "cluster": cell, "service_account_email": email, "role": "roles/iam.workloadIdentityUser",
            "member": f"serviceAccount:{cell_project}.svc.id.goog[{namespace}/{ksa}]",
            "namespace": namespace, "ksa": ksa})


def derive(reg):
    plan = Plan()
    inv = reg.inventory
    cells, pools = inv["gke_cells"], inv["sql_pools"]
    products = {slug: p for slug, (_, p) in reg.products.items()}

    # ---------------- Dedicated subscriptions (per tenant, per environment) ----------------
    for tenant, (_, t) in sorted(reg.tenants.items()):
        for product, sub in sorted(t["subscriptions"].items()):
            p = products[product]
            if p["deployment_model"] != "dedicated":
                continue
            db = p.get("database")
            res = p.get("resources", {})
            for env in [e for e in ENVS if e in sub["versions"]]:
                tier = env_tier(env)
                project = f"t-{tenant}-{tier}"
                purposes = ["app", "mig"] if db else ["app"]
                if db and db.get("readonly_identity"):
                    purposes.append("ro")
                ids = []
                for purpose in purposes:
                    aid = tenant_sa_id(tenant, product, env, purpose)
                    ids.append((purpose, aid, _add_sa(plan, account_id=aid, project=project, tenant=tenant,
                                                      product=product, env=env, purpose=purpose,
                                                      model="dedicated", runtime=p["runtime"])))
                email = {pu: e for pu, _, e in ids}
                labels = {"tenant": tenant, "product": product, "env": env, "env_tier": tier,
                          "isolation_tier": t["isolation_tier"], "deployment_model": "dedicated"}
                pl = sub["placement"][env]
                if p["runtime"] == "gke":
                    cell = pl["gke"]
                    binds = [(product, email["app"])] + ([(f"{product}-migrate", email["mig"])] if "mig" in email else [])
                    _gke(plan, cell=cell, cell_project=cells[cell]["project"],
                         namespace=f"{tenant}-{product}-{env}", labels=labels, bindings=binds)
                if db:
                    pool = pl["sql"]
                    pproj = pools[pool]["project"]
                    database = f"{tenant}_{product}"
                    plan.add("cloud_sql_databases", f"{pool}/{database}", {
                        "pool": pool, "pool_project": pproj, "database": database, "tenant": tenant,
                        "product": product, "env": env, "charset": "utf8mb4", "collation": "utf8mb4_0900_ai_ci"})
                    _db_identities(plan, pool=pool, pool_project=pproj, databases=[database], env=env,
                                   entries=ids, connect_group=sqlconn_group(pproj), connect_project=pproj)
                for b in res.get("buckets", []):
                    bucket = f"{tenant}-{product}-{env}-{b}"
                    for purpose, role in (("app", "roles/storage.objectAdmin"), ("ro", "roles/storage.objectViewer")):
                        if purpose in email:
                            plan.add("resource_iam", f"bucket/{bucket}/{role}/{email[purpose]}", {
                                "project": project, "resource_type": "storage_bucket", "resource": bucket,
                                "tenant": tenant, "role": role, "member": f"serviceAccount:{email[purpose]}"})
                for s in res.get("secrets", []):
                    secret = f"{product}-{env}-{s}"
                    plan.add("resource_iam", f"secret/{project}/{secret}/{email['app']}", {
                        "project": project, "resource_type": "secret", "resource": secret, "tenant": tenant,
                        "role": "roles/secretmanager.secretAccessor", "member": f"serviceAccount:{email['app']}"})

    # ---------------- Shared / Cohort products (product identity, DB per tenant) -------------
    # One product identity per (cohort,) environment reaches every subscribed tenant's database in that
    # deployment. Customer data is still in separate MySQL databases, but the SAME identity can read all of
    # them: tenant isolation is enforced by the application (ADR-006 rev. 3), and the plan marks it so.
    for product, p in sorted(products.items()):
        model = p["deployment_model"]
        if model == "dedicated":
            continue
        subscribers = sorted(t for t, (_, td) in reg.tenants.items() if product in td["subscriptions"])
        if not subscribers:
            continue
        # deployments: shared -> one per env; cohort -> one per (cohort, env) in use
        deployments = set()
        for t in subscribers:
            sub = reg.tenants[t][1]["subscriptions"][product]
            if model == "shared":
                deployments.update((None, e) for e in ENVS)
            else:
                deployments.update((c, e) for e, c in sub["cohort"].items())
        for cohort, env in sorted(deployments, key=lambda x: (x[0] or "", ENVS.index(x[1]))):
            tier = env_tier(env)
            project = f"p-{product}-{tier}"
            base = f"{product}-{cohort}-{env}" if cohort else f"{product}-{env}"
            in_deployment = [t for t in subscribers if model == "shared"
                             or reg.tenants[t][1]["subscriptions"][product]["cohort"].get(env) == cohort]
            purposes = ["app", "mig"] if p.get("database") else ["app"]
            ids = []
            for purpose in purposes:
                aid = base + {"app": "", "mig": "-mig"}[purpose]
                ids.append((purpose, aid, _add_sa(plan, account_id=aid, project=project, tenant=None,
                                                  product=product, env=env, purpose=purpose, model=model,
                                                  runtime=p["runtime"], tenants=in_deployment)))
            if p["runtime"] == "gke":
                cell = next(c for c, v in sorted(cells.items()) if v["env"] == env)
                ns = f"coh-{product}-{cohort}-{env}" if cohort else f"shr-{product}-{env}"
                _gke(plan, cell=cell, cell_project=cells[cell]["project"], namespace=ns,
                     labels={"tenant": "multi", "product": product, "env": env, "env_tier": tier,
                             "deployment_model": model}, bindings=[(product, ids[0][2])])
            if p.get("database"):
                pool = product_pool_for(inv, product, env)   # registered product-owned pool (validator rule R17)
                if pool is None:
                    raise ValueError(f"no registered product pool for {product}/{env}")
                pool_project = inv["product_sql_pools"][pool]["project"]
                for t in in_deployment:
                    plan.add("cloud_sql_databases", f"{pool}/{t}_{product}", {
                        "pool": pool, "pool_project": pool_project, "database": f"{t}_{product}", "tenant": t,
                        "product": product, "env": env, "charset": "utf8mb4", "collation": "utf8mb4_0900_ai_ci"})
                _db_identities(plan, pool=pool, pool_project=pool_project,
                               databases=[f"{t}_{product}" for t in in_deployment],
                               env=env, entries=ids, connect_group=None, connect_project=pool_project,
                               isolation_boundary="application")
    return plan.to_dict()


def summary(plan):
    return {k: len(v) for k, v in plan.items() if isinstance(v, dict)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("registry", nargs="?", default="registry")
    ap.add_argument("-o", "--output", default="build/identity-plan.json")
    args = ap.parse_args(argv)
    reg, findings = validate(args.registry)
    if findings:
        for f in findings:
            print(f, file=sys.stderr)
        print("registry invalid – no plan generated", file=sys.stderr)
        return 1
    plan = derive(reg)
    out = pathlib.Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    for k, v in summary(plan).items():
        print(f"{k:30s} {v}")
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
