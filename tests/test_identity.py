"""D2 – identity plan invariants and golden-file test."""
import json
import pathlib
import re

import pytest

from tools.identity.derive import derive
from tools.registry.validate import validate

GOLDEN = pathlib.Path(__file__).parent / "golden" / "identity-plan.json"


@pytest.fixture(scope="module")
def plan():
    reg, findings = validate(pathlib.Path(__file__).resolve().parent.parent / "registry")
    assert findings == []
    return derive(reg)


def sa_index(plan):
    return {v["email"]: v for v in plan["service_accounts"].values()}


def test_matches_golden_file(plan):
    assert json.loads(json.dumps(plan, sort_keys=True)) == json.loads(GOLDEN.read_text()), \
        "plan changed – review the diff, then refresh tests/golden/identity-plan.json"


def test_deterministic(plan):
    reg, _ = validate("registry")
    assert json.dumps(derive(reg), sort_keys=True) == json.dumps(plan, sort_keys=True)


def test_service_account_ids_fit_iam_limits(plan):
    for sa in plan["service_accounts"].values():
        assert 6 <= len(sa["account_id"]) <= 30
        assert re.fullmatch(r"[a-z]([-a-z0-9]*[a-z0-9])", sa["account_id"])


def test_each_customer_product_env_has_its_own_identity(plan):
    # ABC Payroll Prod and XYZ Payroll Prod must not share an identity (C. Workload identities)
    ded = [s for s in plan["service_accounts"].values() if s["deployment_model"] == "dedicated"]
    keys = [(s["tenant"], s["product"], s["env"], s["purpose"]) for s in ded]
    assert len(keys) == len(set(keys))
    assert len({s["email"] for s in ded}) == len(ded)


def test_tenant_identities_live_in_own_tenant_project_and_tier(plan):
    for s in plan["service_accounts"].values():
        if s["deployment_model"] == "dedicated":
            assert s["project"] == f"t-{s['tenant']}-{s['env_tier']}"
            assert s["account_id"].startswith(f"{s['tenant']}-{s['product']}-{s['env']}")


def test_mysql_usernames_unique_per_pool(plan):
    seen = {}
    for u in plan["cloud_sql_iam_users"].values():
        key = (u["pool"], u["user"])
        assert key not in seen, f"MySQL username collision {key}"
        seen[key] = u["sa_email"]


def test_workload_groups_hold_only_service_accounts_and_stay_in_one_tier(plan):
    sas = sa_index(plan)
    for m in plan["group_memberships"].values():
        assert m["group"].startswith("grp-wl-")
        assert m["member_type"] == "SERVICE_ACCOUNT" and m["member"] in sas
        group_tier = m["group"].split("-")[3]           # grp-wl-sqlconn-<tier>-NN
        assert sas[m["member"]]["env_tier"] == group_tier, f"{m['member']} crosses tiers"


def test_workload_groups_carry_no_data_roles(plan):
    allowed = {"roles/cloudsql.client", "roles/cloudsql.instanceUser"}
    for m in plan["group_memberships"].values():
        assert set(m["grants_via_group"]) <= allowed


def test_dedicated_data_grants_never_cross_tenants(plan):
    # Holds for single-tenant (Dedicated) identities only. Shared/Cohort identities are multi-tenant by
    # design (application-level isolation) – see the tests at the end of this file.
    sas = sa_index(plan)
    for r in plan["resource_iam"].values():
        assert sas[r["member"].removeprefix("serviceAccount:")]["tenant_scope"] == "single"
        member = r["member"].removeprefix("serviceAccount:")
        assert sas[member]["tenant"] == r["tenant"], f"{member} granted on {r['resource']}"
        assert r["resource"].startswith(f"{r['tenant']}-") or r["resource_type"] == "secret"
        assert r["project"] == sas[member]["project"]


def test_database_users_only_on_own_tenant_databases(plan):
    sas = sa_index(plan)
    for u in plan["cloud_sql_iam_users"].values():
        sa = sas[u["sa_email"]]
        if sa["deployment_model"] == "dedicated":
            assert u["databases"] == [f"{sa['tenant']}_{sa['product']}"]
            assert u["user"] == sa["account_id"]                  # MySQL username = SA local part (M1)


def test_workload_identity_maps_namespace_to_same_tenant(plan):
    sas = sa_index(plan)
    for b in plan["workload_identity_bindings"].values():
        sa = sas[b["service_account_email"]]
        if sa["deployment_model"] == "dedicated":
            assert b["namespace"] == f"{sa['tenant']}-{sa['product']}-{sa['env']}"
            assert b["cluster"].startswith(f"gke-{sa['env']}-")
        assert b["member"].endswith(f"[{b['namespace']}/{b['ksa']}]")
        assert sa["purpose"] in ("app", "mig")                    # read-only identity gets no KSA


def test_prod_and_nonprod_never_share_projects_or_pools(plan):
    sas = sa_index(plan)
    for u in plan["cloud_sql_iam_users"].values():
        tier = sas[u["sa_email"]]["env_tier"]
        assert ("prd" in u["pool_project"].split("-")) == (tier == "prd")


def test_removing_a_subscription_removes_its_identities(tmp_path):
    import shutil, yaml
    root = tmp_path / "registry"
    shutil.copytree("registry", root)
    f = root / "tenants" / "xyz.yaml"
    data = yaml.safe_load(f.read_text())
    del data["subscriptions"]["crm"]
    f.write_text(yaml.safe_dump(data, sort_keys=False))
    reg, findings = validate(root)
    assert findings == []
    plan = derive(reg)
    assert not [k for k in plan["service_accounts"] if "xyz-crm" in k]
    assert not [k for k in plan["group_memberships"] if "xyz-crm" in k]


# ---------------- Shared / Cohort: explicit application-level isolation ----------------------
def test_every_identity_declares_its_isolation_boundary(plan):
    for sa in plan["service_accounts"].values():
        if sa["deployment_model"] == "dedicated":
            assert (sa["tenant_scope"], sa["isolation_boundary"], sa["served_tenants"]) == \
                ("single", "identity-and-database", [sa["tenant"]])
        else:
            assert (sa["tenant_scope"], sa["isolation_boundary"]) == ("multi", "application")
            assert sa["tenant"] is None and sa["served_tenants"]


def test_multi_tenant_db_access_is_labelled_and_bounded(plan):
    """A Shared/Cohort identity may reach several tenants' databases – but only databases of its own product,
    only on its own registered product pool, only for the tenants it serves, and the entry says so."""
    sas = sa_index(plan)
    inv_pools = _inventory()["product_sql_pools"]
    for u in plan["cloud_sql_iam_users"].values():
        sa = sas[u["sa_email"]]
        if sa["tenant_scope"] == "single":
            assert u["isolation_boundary"] == "identity-and-database" and len(u["databases"]) == 1
            continue
        assert u["isolation_boundary"] == "application"
        assert u["pool"] in inv_pools and inv_pools[u["pool"]]["owner_product"] == sa["product"]
        assert inv_pools[u["pool"]]["env"] == sa["env"]
        assert u["pool_project"] == inv_pools[u["pool"]]["project"]
        assert u["databases"] == sorted(f"{t}_{sa['product']}" for t in sa["served_tenants"])


def test_dedicated_identities_never_on_product_pools_and_vice_versa(plan):
    sas = sa_index(plan)
    for u in plan["cloud_sql_iam_users"].values():
        on_product_pool = u["pool"].startswith("psql-")
        assert on_product_pool == (sas[u["sa_email"]]["tenant_scope"] == "multi")


def _inventory():
    import yaml
    return yaml.safe_load(pathlib.Path("registry/platform/inventory.yaml").read_text())


def _plan_for(reg_fixture):
    r, findings = validate(reg_fixture.root)
    assert findings == [], [str(f) for f in findings]
    return derive(r)


def test_two_customers_on_same_shared_product(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d["subscriptions"].update(notify={"config": {"sender_domain": "xyz.example.com"}}))
    plan = _plan_for(reg)
    sa = plan["service_accounts"]["p-notify-prd/notify-prd"]
    assert sa["served_tenants"] == ["abc", "xyz"] and sa["isolation_boundary"] == "application"
    user = plan["cloud_sql_iam_users"]["psql-notify-prd-01/notify-prd"]
    # Separate databases per customer, but ONE identity can reach both: not identity-level isolation.
    assert user["databases"] == ["abc_notify", "xyz_notify"]
    assert {"psql-notify-prd-01/abc_notify", "psql-notify-prd-01/xyz_notify"} <= set(plan["cloud_sql_databases"])
    # no per-customer identity is created for a Shared product
    assert not [k for k in plan["service_accounts"] if k.split("/")[1].startswith(("abc-notify", "xyz-notify"))]


def test_two_customers_in_same_cohort_share_one_identity(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d["subscriptions"].update(ledger={"cohort": {"dev": "v4", "stg": "v4", "uat": "v4", "prd": "v3"}}))
    plan = _plan_for(reg)
    assert plan["service_accounts"]["p-ledger-prd/ledger-v3-prd"]["served_tenants"] == ["abc", "xyz"]
    assert plan["cloud_sql_iam_users"]["psql-ledger-prd-01/ledger-v3-prd"]["databases"] == ["abc_ledger", "xyz_ledger"]


def test_customers_in_different_cohorts_do_not_share_an_identity(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d["subscriptions"].update(ledger={"cohort": {"dev": "v4", "stg": "v4", "uat": "v4", "prd": "v4"}}))
    plan = _plan_for(reg)
    assert plan["cloud_sql_iam_users"]["psql-ledger-prd-01/ledger-v3-prd"]["databases"] == ["abc_ledger"]
    assert plan["cloud_sql_iam_users"]["psql-ledger-prd-01/ledger-v4-prd"]["databases"] == ["xyz_ledger"]


def test_generated_product_pools_are_registered(plan):
    inv = _inventory()
    for key in plan["cloud_sql_databases"]:
        pool = key.split("/")[0]
        assert pool in inv["sql_pools"] or pool in inv["product_sql_pools"], pool
