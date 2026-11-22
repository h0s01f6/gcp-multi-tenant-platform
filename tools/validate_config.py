#!/usr/bin/env python3
"""Validates config/ before Terraform or Argo CD ever see it. Run in CI on every PR.

Checks
  * tenant.yaml: required keys, unique subnet_index, gke mode/cluster per env, dedicated index
  * release files: path matches content, product exists, runtime matches catalog,
    version is supported (N-2 window) or a customer patch build of a supported version,
    GKE cluster matches the tenant's tier, canary versions supported
  * data sharing only targets this customer's own environments
"""
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent / "config"
ENVS = ["dev", "stage", "uat", "prod"]
PATCH = re.compile(r"^(?P<base>\d+\.\d+\.\d+)(?:-(?P<cust>[a-z0-9]+)\.\d+)?$")

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def check_version(where: str, customer: str, product: str, version: str, catalog: dict) -> None:
    m = PATCH.match(str(version))
    if not m:
        err(f"{where}: version '{version}' is not semver or <semver>-<customer>.<n>")
        return
    if m.group("cust") and m.group("cust") != customer:
        err(f"{where}: patch build '{version}' belongs to another customer")
    if m.group("base") not in catalog[product]["supported"]:
        err(f"{where}: {product} {m.group('base')} is outside the support window {catalog[product]['supported']}")


def main() -> int:
    platform = yaml.safe_load((ROOT / "platform.yaml").read_text())
    catalog = yaml.safe_load((ROOT / "catalog" / "products.yaml").read_text())["products"]
    pooled = {p["name"] for pools in platform["gke_pools"].values() for p in pools}
    subnet_index: dict[int, str] = {}
    dedicated_index: dict[tuple, str] = {}
    n_releases = 0

    for tdir in sorted(p for p in (ROOT / "tenants").iterdir() if p.is_dir()):
        cust = tdir.name
        tf = tdir / "tenant.yaml"
        if not tf.exists():
            err(f"{cust}: missing tenant.yaml")
            continue
        t = yaml.safe_load(tf.read_text())
        if t.get("customer") != cust:
            err(f"{tf}: customer '{t.get('customer')}' != directory '{cust}'")
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,11}", cust):
            err(f"{cust}: slug must be 2-12 chars [a-z0-9-] (project ID length)")
        idx = t.get("network", {}).get("subnet_index")
        if not isinstance(idx, int) or not 0 <= idx < 1024:
            err(f"{cust}: network.subnet_index must be an int in [0, 1024)")
        elif idx in subnet_index:
            err(f"{cust}: subnet_index {idx} already used by {subnet_index[idx]}")
        else:
            subnet_index[idx] = cust

        for env in ENVS:
            g = t.get("gke", {}).get(env)
            if not g:
                err(f"{cust}: gke.{env} missing")
                continue
            if g["mode"] == "pooled" and g["cluster"] not in pooled:
                err(f"{cust}: gke.{env}.cluster '{g['cluster']}' is not a pooled cluster in platform.yaml")
            if g["mode"] == "pooled" and not g["cluster"].startswith(f"gke-{env}-"):
                err(f"{cust}: gke.{env} points at a cluster of another environment")
            if g["mode"] == "dedicated":
                di = g.get("dedicated_index")
                if not isinstance(di, int) or not 0 <= di < 32:
                    err(f"{cust}: gke.{env}.dedicated_index must be an int in [0, 32)")
                elif (env, di) in dedicated_index:
                    err(f"{cust}: dedicated_index {di} in {env} already used by {dedicated_index[(env, di)]}")
                else:
                    dedicated_index[(env, di)] = cust

        ds = t.get("data_sharing", {})
        for key in ("masked_from_prod_to", "raw_from_prod_to"):
            for env in ds.get(key, []) or []:
                if env not in ENVS or env == "prod":
                    err(f"{cust}: data_sharing.{key} has invalid target '{env}'")

        for rf in sorted(tdir.glob("*/*.yaml")):
            env, product = rf.parent.name, rf.stem
            where = str(rf.relative_to(ROOT))
            if env not in ENVS:
                err(f"{where}: unknown environment directory")
                continue
            r = yaml.safe_load(rf.read_text())
            n_releases += 1
            for k, expected in (("customer", cust), ("env", env), ("product", product)):
                if r.get(k) != expected:
                    err(f"{where}: {k}='{r.get(k)}' does not match path ('{expected}')")
            if product not in catalog:
                err(f"{where}: product '{product}' not in catalog")
                continue
            if r.get("runtime") != catalog[product]["runtime"]:
                err(f"{where}: runtime '{r.get('runtime')}' != catalog '{catalog[product]['runtime']}'")
            check_version(where, cust, product, r.get("version"), catalog)
            if r.get("runtime") == "gke":
                if r.get("cluster") != t["gke"][env]["cluster"]:
                    err(f"{where}: cluster '{r.get('cluster')}' != tenant.yaml gke.{env}.cluster")
                if not r.get("chartVersion"):
                    err(f"{where}: chartVersion is required for gke releases")
            canary = (r.get("cloudrun") or {}).get("canary")
            if canary:
                check_version(f"{where} (canary)", cust, product, canary["version"], catalog)
                if not 0 < canary.get("percent", 0) < 100:
                    err(f"{where}: canary.percent must be between 1 and 99")

    if errors:
        print("Config validation FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"Config OK: {len(subnet_index)} customers, {n_releases} release files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
