#!/usr/bin/env python3
"""Turns a git diff into the minimal Terraform matrix, so a PR touching one customer
plans/applies only that customer's state (blast radius = one customer-env).

Usage: changed_tenants.py <base-ref> [--nonprod-only]   -> JSON {"base": [...], "env": [...]}
PR plans use --nonprod-only: the prod Terraform identity is only reachable from the
protected "prod" GitHub environment, where prod is planned and applied after approval.
"""
import json
import pathlib
import subprocess
import sys

ENVS = ["dev", "stage", "uat", "prod"]
root = pathlib.Path(__file__).resolve().parent.parent
args = [a for a in sys.argv[1:] if not a.startswith("--")]
base_ref = args[0] if args else "origin/main"
nonprod_only = "--nonprod-only" in sys.argv
files = subprocess.run(["git", "diff", "--name-only", f"{base_ref}...HEAD"],
                       capture_output=True, text=True, check=True, cwd=root).stdout.split()

all_tenants = sorted(p.name for p in (root / "config/tenants").iterdir() if p.is_dir())
base, env = set(), set()
for f in files:
    parts = f.split("/")
    if f.startswith("terraform/modules/") or f.startswith("terraform/stacks/6-tenant-env/") or f == "config/catalog/products.yaml":
        env |= {(t, e) for t in all_tenants for e in ENVS}
    if f.startswith("terraform/stacks/5-tenant-base/"):
        base |= set(all_tenants)
    if len(parts) >= 4 and parts[:2] == ["config", "tenants"]:
        tenant = parts[2]
        if parts[3] == "tenant.yaml":
            base.add(tenant)
            env |= {(tenant, e) for e in ENVS}
        elif parts[3] in ENVS:
            env.add((tenant, parts[3]))

env = {(t, e) for t, e in env if (root / "config/tenants" / t).exists() and not (nonprod_only and e == "prod")}
if nonprod_only:
    base = set()
print(json.dumps({
    "base": [{"customer": t} for t in sorted(base)],
    "env": [{"customer": t, "env": e} for t, e in sorted(env)],
}))
