#!/usr/bin/env python3
"""Planning calculator for documentation/capacity-model.md (revision 2: Cloud SQL for MySQL, product groups).

Every value under PARAMETERS is an ILLUSTRATIVE planning input, not a company figure.
Change a parameter and re-run:  python3 scripts/capacity_model.py > /tmp/tables.md
"""
import math

# ----------------------------- PARAMETERS (illustrative) -----------------------------
CUSTOMERS = [200, 500]
SCENARIOS = [("Low", 1), ("Baseline", 3), ("Medium", 5), ("High", 10), ("Upper bound", 20)]
CATALOGUE = 20                      # products (assignment: 15-20)
NONPROD_ENVS = 3
RUNTIME_MIX = {"gke": 0.50, "cloudrun": 0.35, "mig": 0.15}       # share of subscriptions
MODEL_MIX = {"dedicated": 0.60, "cohort": 0.20, "shared": 0.20}  # share of products (illustrative only)
COHORTS_PER_PRODUCT = 3
NS_PER_CELL = 1000                  # planning heuristic, not a GCP limit

# Database assumptions
DB_SHARE = 1.0                      # A16: share of subscriptions needing a relational DB (sensitivity: 0.6)
PRODUCT_GROUPS = 5                  # illustrative: 20 products in 5 groups of 4
SPLIT_FRACTION = 0.5                # a product gets its own pool(s) once its DBs fill >= 50% of a pool
#   prod pool instance (illustrative sizing: 8 vCPU / 32 GB, Enterprise Plus, HA)
PRD = dict(tenant_cap=40, max_connections=4000, conn_budget=0.70, conn_per_tenant=20,
           storage_cap_gb=2048, tenant_gb=20, growth=0.30, years=3,
           tables_limit=50000, table_headroom=0.80, tables_per_db=300)
#   non-prod pool instance (illustrative sizing: 4 vCPU / 16 GB, Enterprise, zonal for dev/stg)
NPR = dict(tenant_cap=100, max_connections=2000, conn_budget=0.70, conn_per_tenant=5,
           storage_cap_gb=1024, tenant_gb=5, growth=0.30, years=3,
           tables_limit=50000, table_headroom=0.80, tables_per_db=300)
INSTANCES_PER_POOL_PROJECT = 100    # planning ceiling (documented limit is up to 1,000 per project)
IAM_POLICY_LIMIT = 1500
SAS_PER_DB = 2                      # app identity + migration identity
SCOPE_LIMIT = 375
CORE_INFRA_PROJECTS = 12            # bootstrap-seed, shr-build, shr-artifacts, shr-cicd x2, shr-security,
                                    # net-host x2, plt-gke x2, plt-ingress x2
MIG_MIN_VMS_PRD, MIG_MIN_VMS_NONPROD = 3, 1
PARALLEL_DEPLOYS, MINUTES_PER_DEPLOY = 20, 4
# --------------------------------------------------------------------------------------


def ceil(a, b):
    return math.ceil(a / b) if a > 0 else 0


def effective_cap(p):
    """Tenant databases per pool = the tightest of four constraints."""
    conn = int(p["max_connections"] * p["conn_budget"] // p["conn_per_tenant"])
    size_future = p["tenant_gb"] * (1 + p["growth"]) ** p["years"]
    storage = int(p["storage_cap_gb"] // size_future)
    tables = int(p["tables_limit"] * p["table_headroom"] // p["tables_per_db"])
    caps = {"tenant count": p["tenant_cap"], "connections": conn, "storage/restore": storage, "tables": tables}
    binding = min(caps, key=caps.get)
    return caps[binding], binding, caps


def prod_pools(subs_db, cap):
    per_product = subs_db / CATALOGUE
    per_group = CATALOGUE // PRODUCT_GROUPS
    split = per_product >= SPLIT_FRACTION * cap
    if split:
        return CATALOGUE * ceil(per_product, cap), "per product"
    return PRODUCT_GROUPS * ceil(per_product * per_group, cap), "per product group"


def deployments_mixed(subs):
    per_product = subs / CATALOGUE
    ded = MODEL_MIX["dedicated"] * CATALOGUE * per_product
    coh = MODEL_MIX["cohort"] * CATALOGUE * min(COHORTS_PER_PRODUCT, per_product)
    shr = MODEL_MIX["shared"] * CATALOGUE * min(1, per_product)
    return ded + coh + shr


def row(c, label, p, db_share=DB_SHARE):
    subs = c * min(p, CATALOGUE)
    subs_db = subs * db_share
    cap_p, bind_p, _ = effective_cap(PRD)
    cap_n, bind_n, _ = effective_cap(NPR)
    prd, mode = prod_pools(subs_db, cap_p)
    dr = prd
    npr = NONPROD_ENVS * ceil(subs_db, cap_n)
    prd_projects = ceil(prd + dr, INSTANCES_PER_POOL_PROJECT)
    npr_projects = ceil(npr, INSTANCES_PER_POOL_PROJECT)
    gke_env = subs * RUNTIME_MIX["gke"]
    mig_env = subs * RUNTIME_MIX["mig"]
    shared_cohort_products = round(CATALOGUE * (MODEL_MIX["cohort"] + MODEL_MIX["shared"]))
    obs = 2 * ceil(c + 10, SCOPE_LIMIT)
    return {
        "C": c, "S": label, "P": min(p, CATALOGUE), "subs": subs,
        "ded_deploy": subs * 4, "mixed_deploy": round(deployments_mixed(subs) * 4),
        "cust_dbs": round(subs_db * 4), "wl_ids": subs * 4,
        "ns_env": round(gke_env), "cells_env": ceil(gke_env, NS_PER_CELL), "cells_env_allgke": ceil(subs, NS_PER_CELL),
        "prd": prd, "mode": mode, "dr": dr, "npr": npr, "total": prd + dr + npr,
        "prd_proj": prd_projects, "npr_proj": npr_projects,
        "sa_per_prd_proj": round(subs_db * SAS_PER_DB / max(prd_projects, 1)),
        "tenant_proj": 2 * c, "product_proj_ded": 0, "product_proj_mix": 2 * shared_cohort_products,
        "infra_proj": CORE_INFRA_PROJECTS + prd_projects + npr_projects + obs,
        "mig_vms": round(mig_env * MIG_MIN_VMS_PRD + mig_env * NONPROD_ENVS * MIG_MIN_VMS_NONPROD),
        "patch_h": round(subs / CATALOGUE * 4 * MINUTES_PER_DEPLOY / PARALLEL_DEPLOYS / 60, 1),
        "cap_p": cap_p, "bind_p": bind_p, "cap_n": cap_n, "bind_n": bind_n,
    }


def table(headers, keys, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        out.append("| " + " | ".join(f"{r[k]:,}" if isinstance(r[k], int) else str(r[k]) for k in keys) + " |")
    return "\n".join(out)


def cap_table():
    lines = ["| Pool | Tenant-count cap | Connection cap | Storage/restore cap (yr-3 size) | Table cap | **Effective tenants per pool** | Binding constraint |",
             "|---|---|---|---|---|---|---|"]
    for name, p in (("Prod (8 vCPU / 32 GB, illustrative)", PRD), ("Non-prod (4 vCPU / 16 GB, illustrative)", NPR)):
        cap, bind, caps = effective_cap(p)
        lines.append(f"| {name} | {caps['tenant count']} | {caps['connections']} "
                     f"({p['max_connections']} × {int(p['conn_budget']*100)}% ÷ {p['conn_per_tenant']}) | "
                     f"{caps['storage/restore']} ({p['storage_cap_gb']} GB ÷ {p['tenant_gb']} GB grown {int(p['growth']*100)}%/yr × {p['years']} yrs) | "
                     f"{caps['tables']} ({p['tables_limit']:,} × {int(p['table_headroom']*100)}% ÷ {p['tables_per_db']}) | **{cap}** | {bind} |")
    return "\n".join(lines)


def sensitivity():
    lines = ["| Avg prod tenant DB size today | Tables per tenant DB | Effective prod tenants per pool | Binding | Prod pools at 500 × 10 |",
             "|---|---|---|---|---|"]
    for gb in (10, 20, 50, 100):
        for tables in (300, 1000, 2000):
            p = dict(PRD, tenant_gb=gb, tables_per_db=tables)
            cap, bind, _ = effective_cap(p)
            prd, _ = prod_pools(5000 * DB_SHARE, cap)
            lines.append(f"| {gb} GB | {tables:,} | {cap} | {bind} | {prd:,} |")
    return "\n".join(lines)


if __name__ == "__main__":
    rows = [row(c, s, p) for c in CUSTOMERS for s, p in SCENARIOS]
    rows60 = [row(c, s, p, db_share=0.6) for c in CUSTOMERS for s, p in SCENARIOS]
    print("### T1 Subscriptions, deployments, databases and identities (4 environments)\n")
    print(table(["Customers", "Scenario", "Avg products", "Subscriptions", "Infra deployments – all Dedicated",
                 "Infra deployments – illustrative mixed models", "Customer databases (100% need a DB)",
                 "Per-customer workload identities (Dedicated)"],
                ["C", "S", "P", "subs", "ded_deploy", "mixed_deploy", "cust_dbs", "wl_ids"], rows))
    print("\n### T2 GKE namespaces per environment cluster (50% GKE, illustrative)\n")
    print(table(["Customers", "Scenario", "Namespaces per env cluster", "Cells per env (50% GKE)", "Cells per env (100% GKE)"],
                ["C", "S", "ns_env", "cells_env", "cells_env_allgke"], rows))
    print("\n### T3 Effective tenant databases per pool\n")
    print(cap_table())
    print("\n### T4 Cloud SQL for MySQL instances – product-group pooling (every subscription needs a DB, A16 = 100%)\n")
    print(table(["Customers", "Scenario", "Prod pools", "Prod pooling mode", "DR replicas", "Non-prod pools (3 envs)",
                 "Total instances", "Prod pool projects", "Non-prod pool projects"],
                ["C", "S", "prd", "mode", "dr", "npr", "total", "prd_proj", "npr_proj"], rows))
    print("\n### T4b Same, if only 60% of subscriptions need a relational DB (A16 sensitivity)\n")
    print(table(["Customers", "Scenario", "Prod pools", "DR replicas", "Non-prod pools", "Total instances"],
                ["C", "S", "prd", "dr", "npr", "total"], rows60))
    print("\n### T5 Sensitivity – prod tenant DB size and table count (500 customers × 10 products)\n")
    print(sensitivity())
    print("\n### T6 Projects by category\n")
    print(table(["Customers", "Scenario", "Tenant projects (fixed: 2 per customer)",
                 "Product projects (0 if all Dedicated; illustrative mix)", "Infrastructure projects (core + SQL pool + observability shards)"],
                ["C", "S", "tenant_proj", "product_proj_mix", "infra_proj"], rows))
    print("\n### T7 IAM fallback check, MIG floor and fleet patching\n")
    print(table(["Customers", "Scenario", "SA principals per prod pool project if instanceUser must be per-SA (limit 1,500)",
                 "MIG VMs minimum floor", "Patch one product fleet-wide (h, 20 parallel)"],
                ["C", "S", "sa_per_prd_proj", "mig_vms", "patch_h"], rows))
