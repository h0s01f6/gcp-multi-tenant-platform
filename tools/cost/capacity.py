"""Stage 8 – capacity planning against the live registry: utilisation of cells, pools, pool projects, metrics scopes,
SLO services and uptime-check budgets, with the scale-out trigger for each (cost/cost-model.yaml `capacity`).

Usage:  python3 -m tools.cost.capacity [--registry registry]
Used by the pipeline planner as PL05: a placement that pushes a resource above `max` is refused in the pull request;
above `warn` the report lists the planned scale-out (new cell / pool / project / scope shard) – done by a platform PR.
Rules
  CP01 utilisation <= max for every resource (also reported by the planner as PL05)
  CP02 every capacity entry has a limit, warn < max and an action
Status: implemented + locally tested (tests/test_cost.py).
"""
import argparse
import math
import pathlib
import sys

from tools.cost.model import capacity_model
from tools.registry.loader import load_yaml
from tools.registry.validate import Finding, validate

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV_TIER = {"dev": "nonprd", "stg": "nonprd", "uat": "nonprd", "prd": "prd"}


def config(root=ROOT):
    return load_yaml(pathlib.Path(root) / "cost" / "cost-model.yaml")["capacity"]


def utilisation(reg, root=ROOT):
    """-> list of {resource, name, used, limit, warn, max, action}."""
    cfg, cm = config(root), capacity_model()
    cap_prd, _, _ = cm.effective_cap(cm.PRD)
    cap_npr, _, _ = cm.effective_cap(cm.NPR)
    inv = reg.inventory
    pools = {**inv["sql_pools"], **inv.get("product_sql_pools", {})}
    ns, dbs, svc, hosts = {c: 0 for c in inv["gke_cells"]}, {p: 0 for p in pools}, {}, {}
    for tenant, (_, t) in reg.tenants.items():
        hosts[tenant] = 0
        for product, sub in t["subscriptions"].items():
            for env, pl in (sub.get("placement") or {}).items():
                if pl.get("gke"):
                    ns[pl["gke"]] += 1
                if pl.get("sql"):
                    dbs[pl["sql"]] += 1
            envs = set((sub.get("versions") or sub.get("cohort") or {}).keys()) or {"prd"}
            if "prd" in envs:
                svc[product] = svc.get(product, 0) + 1
                hosts[tenant] += 1
    out = []

    def add(resource, name, used, limit):
        c = cfg[resource]
        out.append({"resource": resource, "name": name, "used": used, "limit": limit, "warn": c["warn"],
                    "max": c["max"], "action": c["action"], "ratio": used / limit if limit else 0.0})

    for cell, n in sorted(ns.items()):
        add("namespaces_per_cell", cell, n, cfg["namespaces_per_cell"]["limit"])
    for pool, n in sorted(dbs.items()):
        add("tenants_per_pool", pool, n, cap_prd if pools[pool]["env"] == "prd" else cap_npr)
    per_project = {}
    for pool, m in pools.items():
        per_project[m["project"]] = per_project.get(m["project"], 0) + 1
    for proj, n in sorted(per_project.items()):
        add("instances_per_pool_project", proj, n, cfg["instances_per_pool_project"]["limit"])
    for tier in ("prd", "nonprd"):
        projects = len(reg.tenants) + sum(1 for p in pools.values() if ENV_TIER[p["env"]] == tier) + 4
        for i, n in enumerate(scope_shards(projects, cfg), 1):
            add("projects_per_metrics_scope", f"plt-obs-{tier}-{i:02d}", n, cfg["projects_per_metrics_scope"]["limit"])
    for product, n in sorted(svc.items()):
        add("slos_per_service", f"svc-{product}-prd", n, cfg["slos_per_service"]["limit"])
    for tenant, n in sorted(hosts.items()):
        add("uptime_checks_per_project", f"t-{tenant}-prd", n, cfg["uptime_checks_per_project"]["limit"])
    return out


def scope_shards(projects, cfg=None):
    """Split N monitored projects over scoping projects so each stays at or below the warn level."""
    cfg = cfg or config()
    c = cfg["projects_per_metrics_scope"]
    per = int(c["limit"] * c["warn"])
    n = max(1, math.ceil(projects / per))
    base, extra = divmod(projects, n)
    return [base + (1 if i < extra else 0) for i in range(n)]


def check_placements(reg, root=ROOT):
    """PL05 for the planner: refused placements (above max)."""
    return [Finding("PL05", "registry", f"{u['resource']} {u['name']}: {u['used']}/{u['limit']} above "
                                        f"{int(u['max'] * 100)} % – {u['action']}")
            for u in utilisation(reg, root) if u["ratio"] > u["max"]]


def check(root=ROOT):
    f = []
    for k, c in config(root).items():
        if not c.get("action") or not c.get("limit") or not (0 < c["warn"] < c["max"]):
            f.append(Finding("CP02", "cost/cost-model.yaml", f"capacity {k}: limit, warn < max and action required"))
    reg, _ = validate(pathlib.Path(root) / "registry")
    f += [Finding("CP01", x.path, x.message) for x in check_placements(reg, root)]
    return f


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registry", default=str(ROOT / "registry"))
    a = ap.parse_args(argv)
    reg, _ = validate(a.registry)
    rows = utilisation(reg)
    warn = [u for u in rows if u["ratio"] >= u["warn"]]
    for u in warn:
        print(f"SCALE {u['resource']} {u['name']}: {u['used']}/{u['limit']} ({u['ratio']:.0%}) -> {u['action']}")
    findings = check()
    for x in findings:
        print(x)
    top = max(rows, key=lambda u: u["ratio"])
    print(f"{len(rows)} capacity items, highest {top['resource']} {top['name']} {top['ratio']:.0%}, "
          f"{len(warn)} scale-out trigger(s); {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
