"""D1 – tenant registry validator tests. Each test breaks one rule and expects exactly that rule ID."""
import pytest

from tools.registry.validate import validate


def rules(r):
    _, findings = validate(r.root)
    return {f.rule for f in findings}, findings


def test_example_registry_is_valid(reg):
    got, findings = rules(reg)
    assert findings == [], [str(f) for f in findings]


# ---- duplicate-entry handling (Stage 2 observation) ----------------------------------------
def test_duplicate_subscription_key_in_one_file_is_rejected(reg):
    text = (reg.root / "tenants/xyz.yaml").read_text()
    # declare 'crm' a second time inside subscriptions
    text += "  crm:\n    versions: { dev: 3.2.0 }\n    placement: { dev: { sql: sql-dev-01 } }\n"
    reg.raw("tenants/xyz.yaml", text)
    got, findings = rules(reg)
    assert "R01" in got and any("duplicate key 'crm'" in f.message for f in findings)


def test_duplicate_env_key_is_rejected(reg):
    text = (reg.root / "tenants/xyz.yaml").read_text().replace(
        "versions: { dev: 3.1.1,", "versions: { dev: 3.1.1, dev: 3.0.5,")
    reg.raw("tenants/xyz.yaml", text)
    assert "R01" in rules(reg)[0]


def test_same_tenant_in_two_files_is_rejected(reg):
    reg.write("tenants/xyz2.yaml", reg.read("tenants/xyz.yaml"))
    got, _ = rules(reg)
    assert {"R03", "R04"} <= got


def test_duplicate_product_file_is_rejected(reg):
    reg.write("products/crm2.yaml", reg.read("products/crm.yaml"))
    assert "R04" in rules(reg)[0]


# ---- schema and structure ------------------------------------------------------------------
def test_unknown_field_fails_schema(reg):
    reg.edit("tenants/abc.yaml", lambda d: d.update(region="asia-south1"))
    assert rules(reg)[0] == {"R02"}


def test_version_written_as_number_fails_schema(reg):
    reg.edit("tenants/abc.yaml", lambda d: d["subscriptions"]["crm"]["versions"].update(dev=3.2))
    assert "R02" in rules(reg)[0]


def test_file_name_must_match_slug(reg):
    reg.write("tenants/abcd.yaml", reg.read("tenants/abc.yaml"))
    (reg.root / "tenants/abc.yaml").unlink()
    assert rules(reg)[0] == {"R03"}


def test_unknown_product(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d["subscriptions"].update(hr={"versions": {"dev": "1.0.0"}}))
    assert "R05" in rules(reg)[0]


# ---- deployment models ---------------------------------------------------------------------
def test_shared_product_must_not_have_versions(reg):
    reg.edit("tenants/abc.yaml", lambda d: d["subscriptions"]["notify"].update(versions={"dev": "1.4.2"}))
    assert "R06" in rules(reg)[0]


def test_cohort_product_needs_known_cohort(reg):
    reg.edit("tenants/abc.yaml", lambda d: d["subscriptions"]["ledger"]["cohort"].update(prd="v9"))
    assert "R06" in rules(reg)[0]


def test_dedicated_product_needs_versions(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d["subscriptions"]["crm"].pop("versions"))
    assert "R06" in rules(reg)[0]


# ---- promotion and versions ----------------------------------------------------------------
def test_prod_without_uat_breaks_promotion_chain(reg):
    def f(d):
        d["subscriptions"]["crm"]["versions"].pop("uat")
        d["subscriptions"]["crm"]["placement"].pop("uat")
    reg.edit("tenants/xyz.yaml", f)
    assert "R07" in rules(reg)[0]


def test_unsupported_version(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d["subscriptions"]["crm"]["versions"].update(dev="4.0.0"))
    assert "R08" in rules(reg)[0]


def test_blocked_version(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d["subscriptions"]["payroll"]["versions"].update(dev="2.0.0"))
    assert "R08" in rules(reg)[0]


def test_prod_newer_than_uat(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d["subscriptions"]["payroll"]["versions"].update(prd="1.5.9"))
    assert rules(reg)[0] == {"R09"}


# ---- placement -----------------------------------------------------------------------------
def test_missing_placement(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d["subscriptions"]["payroll"]["placement"].pop("stg"))
    assert rules(reg)[0] == {"R10"}


def test_cell_from_wrong_environment(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d["subscriptions"]["payroll"]["placement"]["uat"].update(gke="gke-stg-as1-01"))
    assert rules(reg)[0] == {"R10"}


def test_prod_pool_of_other_product(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d["subscriptions"]["crm"]["placement"]["prd"].update(sql="sql-prd-payroll-01"))
    assert rules(reg)[0] == {"R10"}


def test_unknown_pool(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d["subscriptions"]["crm"]["placement"]["dev"].update(sql="sql-dev-09"))
    assert rules(reg)[0] == {"R10"}


def test_cloudrun_product_with_gke_placement(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d["subscriptions"]["crm"]["placement"]["dev"].update(gke="gke-dev-as1-01"))
    assert rules(reg)[0] == {"R10"}


def test_mysql_version_mismatch(reg):
    reg.edit("platform/inventory.yaml", lambda d: d["sql_pools"]["sql-dev-01"].update(mysql="8.0"))
    assert rules(reg)[0] == {"R10"}


def test_dedicated_tenant_cannot_use_shared_prod_pool(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d.update(isolation_tier="dedicated"))
    assert rules(reg)[0] == {"R16"}


def test_dedicated_tenant_with_own_instance_is_valid(reg):
    reg.edit("platform/inventory.yaml", lambda d: d["sql_pools"].update(
        {"sql-prd-xyz-01": {"env": "prd", "project": "t-xyz-prd", "mysql": "8.4", "dedicated_tenant": "xyz"}}))
    def f(d):
        d["isolation_tier"] = "dedicated"
        d["subscriptions"]["payroll"]["placement"]["prd"]["sql"] = "sql-prd-xyz-01"
        d["subscriptions"]["crm"]["placement"]["prd"]["sql"] = "sql-prd-xyz-01"
    reg.edit("tenants/xyz.yaml", f)
    assert rules(reg)[1] == []


def test_standard_tenant_cannot_use_dedicated_pool(reg):
    reg.edit("platform/inventory.yaml", lambda d: d["sql_pools"].update(
        {"sql-prd-big-01": {"env": "prd", "project": "t-big-prd", "mysql": "8.4", "dedicated_tenant": "big"}}))
    reg.edit("tenants/xyz.yaml", lambda d: d["subscriptions"]["crm"]["placement"]["prd"].update(sql="sql-prd-big-01"))
    assert rules(reg)[0] == {"R16"}


# ---- naming, ownership, reserved keys ------------------------------------------------------
def test_product_slug_too_long_is_caught_in_catalogue(reg):
    p = reg.read("products/crm.yaml")
    p["product"] = "abcdefghijkl"              # 12 chars -> migration SA 31
    reg.write("products/abcdefghijkl.yaml", p)
    assert "R02" in rules(reg)[0]              # schema regex rejects it before any tenant uses it


def test_owner_group_must_match_tenant(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d["owners"].update(technical="grp-hum-cust-abc-support"))
    assert rules(reg)[0] == {"R14"}


def test_reserved_config_key(reg):
    reg.edit("tenants/abc.yaml", lambda d: d["subscriptions"]["payroll"]["config"].update(hostname="xyz.payroll.example.com"))
    assert rules(reg)[0] == {"R13"}


def test_product_group_must_exist(reg):
    reg.edit("products/crm.yaml", lambda d: d["database"].update(pool_group="g9"))
    assert "R15" in rules(reg)[0]


# ---- R17 product-owned pools (Shared / Cohort) ---------------------------------------------
def test_missing_product_pool_is_rejected(reg):
    reg.edit("platform/inventory.yaml", lambda d: d["product_sql_pools"].pop("psql-notify-uat-01"))
    got, findings = rules(reg)
    assert got == {"R17"} and any("notify/uat" in f.message for f in findings)


def test_missing_cohort_pool_only_for_used_environments(reg):
    reg.edit("platform/inventory.yaml", lambda d: d["product_sql_pools"].pop("psql-ledger-prd-01"))
    assert rules(reg)[0] == {"R17"}


def test_product_pool_in_wrong_project(reg):
    reg.edit("platform/inventory.yaml", lambda d: d["product_sql_pools"]["psql-notify-prd-01"].update(project="p-notify-nonprd"))
    assert rules(reg)[0] == {"R17"}


def test_product_pool_owned_by_dedicated_product(reg):
    reg.edit("platform/inventory.yaml", lambda d: d["product_sql_pools"].update(
        {"psql-crm-dev-01": {"env": "dev", "project": "p-crm-nonprd", "mysql": "8.4", "owner_product": "crm"}}))
    assert rules(reg)[0] == {"R17"}


def test_product_pool_name_must_match_owner_and_env(reg):
    def f(d):
        v = d["product_sql_pools"].pop("psql-notify-dev-01")
        d["product_sql_pools"]["psql-notify-stg-02"] = v          # says stg, serves dev
    reg.edit("platform/inventory.yaml", f)
    assert rules(reg)[0] == {"R17"}


def test_tenant_placement_cannot_reference_a_product_pool(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d["subscriptions"]["crm"]["placement"]["dev"].update(sql="psql-notify-dev-01"))
    assert "R02" in rules(reg)[0]           # tenant placement accepts only sql-* pools
