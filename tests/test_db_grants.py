"""D4 – MySQL grant generation."""
import json

import pytest

from tools.db import grants as G
from tools.identity.derive import derive
from tools.registry.validate import validate


@pytest.fixture
def pools(reg):
    r, findings = validate(reg.root)
    assert not findings
    return G.build_pool_plans(derive(r))


def test_every_pool_in_plan_and_static_checks_pass(pools):
    assert len(pools) == 13
    for name, pp in pools.items():
        assert G.check_pool_plan(pp) == [], name


def test_grant_uses_escaped_database_name(pools):
    sql = G.render_sql(pools["sql-prd-payroll-01"])
    assert "ON `abc\\_payroll`.* TO 'r_abc_payroll_app'" in sql
    assert "ON `abc_payroll`.*" not in sql                       # never the unescaped pattern
    assert "*.*" not in sql and "GRANT OPTION" not in sql and "ALL PRIVILEGES" not in sql


def test_roles_are_per_database_and_purpose(pools):
    pp = pools["sql-prd-payroll-01"]
    assert pp["accounts"]["abc-payroll-prd"]["roles"] == ["r_abc_payroll_app"]
    assert pp["accounts"]["abc-payroll-prd-mig"]["roles"] == ["r_abc_payroll_ddl"]
    assert pp["accounts"]["abc-payroll-prd-ro"]["roles"] == ["r_abc_payroll_ro"]
    assert pp["roles"]["r_abc_payroll_ro"]["privileges"] == ["SELECT"]
    assert "CREATE" not in pp["roles"]["r_abc_payroll_app"]["privileges"]   # runtime: no DDL (ISO-07)


def test_sql_is_idempotent_statements_only(pools):
    for pp in pools.values():
        for line in G.render_sql(pp).splitlines():
            if line.startswith(("CREATE DATABASE", "CREATE ROLE", "CREATE TABLE")):
                assert "IF NOT EXISTS" in line, line
            assert not line.startswith(("DROP", "REVOKE", "CREATE USER")), line


def test_wildcard_canary_matches_unescaped_pattern_only():
    from tests.fake_mysql import like
    c = G.wildcard_canary("abc_payroll")
    assert "_" not in c
    assert like("abc_payroll", "abc0payroll")                    # unescaped pattern would match a canary-like name
    assert not like(G.escape_db_pattern("abc_payroll"), "abc0payroll")
    assert like(G.escape_db_pattern("abc_payroll"), "abc_payroll")


def test_dedicated_identity_single_tenant_shared_identity_marked(pools):
    for pp in pools.values():
        for a, s in pp["accounts"].items():
            tenants = {pp["databases"][d]["tenant"] for d in s["databases"]}
            if s["isolation_boundary"] == "identity-and-database":
                assert len(tenants) == 1, a
    sql = G.render_sql(pools["psql-notify-prd-01"])
    assert "application-level tenant isolation" in sql


def test_shared_identity_gets_role_on_every_served_tenant_db(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d["subscriptions"].update(
        {"notify": {"config": {"sender_domain": "xyz.example.com"}}}))
    r, findings = validate(reg.root)
    assert not findings, findings
    pp = G.build_pool_plans(derive(r))["psql-notify-prd-01"]
    assert pp["accounts"]["notify-prd"]["roles"] == ["r_abc_notify_app", "r_xyz_notify_app"]
    assert pp["accounts"]["notify-prd"]["isolation_boundary"] == "application"
    assert G.check_pool_plan(pp) == []


def test_static_check_rejects_cross_tenant_and_forbidden(pools):
    pp = json.loads(json.dumps(pools["sql-prd-payroll-01"]))
    pp["accounts"]["abc-payroll-prd"]["roles"].append("r_xyz_payroll_app")
    pp["roles"]["r_abc_payroll_app"]["privileges"].append("PROCESS")
    errs = G.check_pool_plan(pp)
    assert any("reaches 2 tenants" in e for e in errs)
    assert any("forbidden privileges" in e for e in errs)


def test_invalid_database_name_rejected():
    with pytest.raises(ValueError):
        G.escape_db_pattern("abc%payroll")


@pytest.mark.parametrize("line,expected", [
    ("GRANT USAGE ON *.* TO `abc-payroll-prd`@`%`", ("privs", ("USAGE",), "*.*", "abc-payroll-prd@%", False)),
    ("GRANT `r_a`@`%`,`r_b`@`%` TO `u1`@`%`", ("roles", ("r_a@%", "r_b@%"), "u1@%", False)),
    ("GRANT SELECT ON `abc\\_payroll`.* TO `r`@`%` WITH GRANT OPTION",
     ("privs", ("SELECT",), "abc\\_payroll.*", "r@%", True)),
])
def test_normalise_grant(line, expected):
    assert G.normalise_grant(line) == expected


def test_cli_writes_files(tmp_path, pools):
    plan = tmp_path / "plan.json"
    from tools.registry.validate import validate as v
    import pathlib
    r, _ = v(pathlib.Path(__file__).resolve().parent.parent / "registry")
    plan.write_text(json.dumps(derive(r)))
    assert G.main([str(plan), "-o", str(tmp_path / "sql")]) == 0
    assert (tmp_path / "sql" / "sql-prd-payroll-01.sql").exists()
    assert (tmp_path / "sql" / "sql-prd-payroll-01.expected-grants.json").exists()


def test_isotest_impersonation_stays_in_tier(pools):
    binds = G.isotest_impersonation(pools)
    assert len(binds) == sum(len(p["accounts"]) for p in pools.values())
    for b in binds:
        assert b["role"] == "roles/iam.serviceAccountTokenCreator"
        sa_tier = "nonprd" if "-nonprd.iam." in b["resource"] else "prd"   # SA lives in a <...>-<tier> project
        assert f"isotest-{b['tier']}@shr-cicd-{b['tier']}" in b["member"]
        assert b["tier"] == sa_tier, b
