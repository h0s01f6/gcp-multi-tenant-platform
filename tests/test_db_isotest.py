"""D4 – isolation-test harness, executed against the privilege model in tests/fake_mysql.py (not MySQL)."""
import pytest

from tests.fake_mysql import FakeAdmin, FakeFleet, FakeMySQL
from tools.db import grants as G
from tools.db import isotest as I
from tools.identity.derive import derive
from tools.registry.validate import validate


@pytest.fixture
def pools(reg):
    r, findings = validate(reg.root)
    assert not findings
    return G.build_pool_plans(derive(r))


def provision(pools):
    servers = {}
    for name, pp in pools.items():
        srv = FakeMySQL(name, pp["env"])
        for a in pp["accounts"]:
            srv.add_user(a)                 # Terraform google_sql_user
        srv.apply_script(G.render_sql(pp))  # bootstrap job
        servers[name] = srv
    return servers


def run_tier(pools, servers, tier, cases=None, **fleet_opts):
    cases = I.for_tier(cases or I.generate_cases(pools), pools, tier)
    fleet = FakeFleet(servers, tier)
    for k, v in fleet_opts.items():
        setattr(fleet, k, v)
    return I.report(I.run(cases, fleet, FakeAdmin(servers)))


def failing(rep, check=None):
    return [f for f in rep["failures"] if check is None or f["id"] == check]


def test_all_checks_present(pools):
    ids = {c.id for c in I.generate_cases(pools, removed=[("sql-prd-payroll-01", "old-payroll-prd")])}
    assert ids == {f"ISO-{n:02d}" for n in range(1, 11)}


@pytest.mark.parametrize("tier", ["nonprd", "prd"])
def test_generated_grants_pass_the_gate(pools, tier):
    rep = run_tier(pools, provision(pools), tier)
    assert rep["gate"] == "PASS", rep["failures"][:3]
    assert rep["total"] > 100


def test_iso01_assignment_case_abc_cannot_reach_xyz(pools):
    cases = [c for c in I.generate_cases(pools) if c.id == "ISO-01" and c.actor == "abc-payroll-prd"]
    assert {c.target for c in cases} == {"xyz_payroll"}


def test_unescaped_grant_is_caught_by_iso03(pools):
    servers = provision(pools)
    srv = servers["sql-prd-payroll-01"]
    srv.accounts["r_abc_payroll_app"]["db"] = [("abc_payroll", {"SELECT", "INSERT", "UPDATE", "DELETE", "EXECUTE"})]
    rep = run_tier(pools, servers, "prd")
    assert rep["gate"] == "FAIL"
    assert any(f["target"] == "abc0payroll" for f in failing(rep, "ISO-03"))
    assert failing(rep, "ISO-09")                      # drift is also visible in SHOW GRANTS


def test_cross_tenant_grant_is_caught_by_iso01_02_09(pools):
    servers = provision(pools)
    servers["sql-prd-payroll-01"].accounts["abc-payroll-prd"]["roles"].add("r_xyz_payroll_app")
    rep = run_tier(pools, servers, "prd")
    for check in ("ISO-01", "ISO-02", "ISO-09"):
        assert failing(rep, check), check


def test_global_privileges_are_caught_by_iso05_06(pools):
    servers = provision(pools)
    servers["sql-prd-payroll-01"].accounts["abc-payroll-prd"]["global"] |= {"PROCESS", "CONNECTION_ADMIN", "CREATE USER"}
    rep = run_tier(pools, servers, "prd")
    assert failing(rep, "ISO-05") and failing(rep, "ISO-06")


def test_runtime_ddl_is_caught_by_iso07(pools):
    servers = provision(pools)
    servers["sql-prd-payroll-01"].accounts["abc-payroll-prd"]["roles"].add("r_abc_payroll_ddl")
    rep = run_tier(pools, servers, "prd")
    assert any(f["actor"] == "abc-payroll-prd" for f in failing(rep, "ISO-07"))


def test_foreign_definer_is_caught_by_iso08(pools):
    servers = provision(pools)
    servers["sql-prd-payroll-01"].accounts["abc-payroll-prd-mig"]["global"].add("SET_ANY_DEFINER")
    rep = run_tier(pools, servers, "prd")
    assert any("DEFINER" in f["statement"] for f in failing(rep, "ISO-08"))


def test_missing_tier_boundary_is_caught_by_iso04(pools):
    rep = run_tier(pools, provision(pools), "nonprd", tier_boundary=False)
    assert failing(rep, "ISO-04") and all("tier boundary" in f["detail"] for f in failing(rep, "ISO-04"))


def test_unexpected_account_is_caught_by_iso09(pools):
    servers = provision(pools)
    servers["sql-prd-crm-01"].add_user("leftover-crm-prd")
    rep = run_tier(pools, servers, "prd")
    assert any("leftover-crm-prd" in f["detail"] for f in failing(rep, "ISO-09"))


def test_iso10_offboarded_identity(pools):
    servers = provision(pools)
    removed = [("sql-prd-crm-01", "abc-crm-prd")]
    cases = [c for c in I.generate_cases(pools, removed=removed) if c.id == "ISO-10"]
    # still present -> FAIL
    rep = run_tier(pools, servers, "prd", cases=cases)
    assert rep["gate"] == "FAIL"
    # after DROP USER (Cloud SQL API in reality) -> PASS
    servers["sql-prd-crm-01"].accounts.pop("abc-crm-prd")
    rep = run_tier(pools, servers, "prd", cases=cases)
    assert rep["gate"] == "PASS"


def test_unexpected_success_is_cleaned_up(pools):
    servers = provision(pools)
    servers["sql-prd-payroll-01"].accounts["abc-payroll-prd"]["roles"].add("r_abc_payroll_ddl")
    cleaned = []
    orig = FakeMySQL.admin_exec
    FakeMySQL.admin_exec = lambda self, s: (cleaned.append(s), orig(self, s))[1]
    try:
        run_tier(pools, servers, "prd")
    finally:
        FakeMySQL.admin_exec = orig
    assert any("DROP TABLE IF EXISTS `abc_payroll`.`zz_iso_probe`" in s for s in cleaned)


def test_shared_identity_report_states_application_boundary(pools):
    rep = run_tier(pools, provision(pools), "prd")
    assert "application" in rep["application_boundary_note"]
    shared = [c for c in I.generate_cases(pools) if c.actor == "notify-prd"]
    assert shared and all(c.boundary == "application" for c in shared)


def test_probes_never_read_tenant_rows(pools):
    for c in I.generate_cases(pools):
        if c.kind == "deny" and c.statement.startswith("SELECT"):
            assert "`canary`" in c.statement or "mysql.user" in c.statement
