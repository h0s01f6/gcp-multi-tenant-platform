"""D4 – MySQL grant generation from the identity plan (D2 output).

Usage:  python3 -m tools.db.grants [build/identity-plan.json] [-o build/sql]

For every Cloud SQL pool in the plan this writes:
  <pool>.sql                  idempotent bootstrap SQL, run by sqlboot-<tier>@plt-sql-<tier>-NN (database architecture §6 step 4)
  <pool>.expected-grants.json the exact SHOW GRANTS set per account and role (used by ISO-09 drift check)

What it does NOT do (by design):
  * create IAM database users – Terraform owns google_sql_user (Stage 5); the SQL only grants roles to them
  * revoke drift – drift is detected by ISO-09 and fails the pipeline; repair is a reviewed change
Status: implemented + locally tested (generation logic and a privilege model, see tests/test_db_*.py).
        Not executed against MySQL; SHOW GRANTS formatting is confirmed by cloud test T-M2.
"""
import argparse
import json
import pathlib
import re
import sys

# Privileges per role purpose (database architecture §4). Database-level only: never *.*, never GRANT OPTION.
ROLE_PRIVILEGES = {
    "app": ["SELECT", "INSERT", "UPDATE", "DELETE", "EXECUTE"],
    "ro": ["SELECT"],
    "ddl": ["SELECT", "INSERT", "UPDATE", "DELETE", "EXECUTE", "CREATE", "ALTER", "DROP", "INDEX", "REFERENCES",
            "CREATE VIEW", "SHOW VIEW", "TRIGGER", "CREATE ROUTINE", "ALTER ROUTINE", "EVENT", "LOCK TABLES",
            "CREATE TEMPORARY TABLES"],
}
# Identity purpose (D2) -> role suffix. The migration identity gets the DDL role (ADR-011, §7).
PURPOSE_ROLE = {"app": "app", "mig": "ddl", "ro": "ro"}

# Representative per-account connection budgets (database architecture §8). Shared/Cohort product identities
# serve several tenants, so their budget is per identity, not per tenant. Real values come from the capacity
# model per product; MAX_USER_CONNECTIONS on IAM accounts is cloud test T-M3.
CONNECTION_BUDGET = {
    ("app", "identity-and-database"): 20,
    ("mig", "identity-and-database"): 2,
    ("ro", "identity-and-database"): 5,
    ("app", "application"): 60,
    ("mig", "application"): 2,
}

# Privileges that must never appear for a tenant role or tenant account (ISO-05/09, M2).
FORBIDDEN_PRIVILEGES = {"ALL", "ALL PRIVILEGES", "SUPER", "PROCESS", "FILE", "GRANT OPTION", "CREATE USER",
                        "RELOAD", "SHUTDOWN", "SYSTEM_VARIABLES_ADMIN", "CONNECTION_ADMIN", "SET_USER_ID",
                        "SET_ANY_DEFINER", "ROLE_ADMIN", "SYSTEM_USER", "REPLICATION SLAVE", "REPLICATION CLIENT"}

DB_RE = re.compile(r"^[a-z][a-z0-9]{2,9}_[a-z][a-z0-9]{1,10}$")
USER_RE = re.compile(r"^[a-z][-a-z0-9]{4,30}$")       # MySQL IAM user = SA local part, <= 32 chars (M1)
CANARY_STATIC = ("zz_canary_a", "zz_canary_b")


def escape_db_pattern(db):
    """Database name as a grant pattern: `_` and `%` are wildcards in db-level grants and must be escaped (M2)."""
    if not DB_RE.match(db):
        raise ValueError(f"database name '{db}' does not follow <tenant>_<product>")
    return db.replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%")


def wildcard_canary(db):
    """A real database name that the UNESCAPED pattern of `db` would match (ISO-03).

    `abc_payroll` unescaped matches `abc0payroll`. No prefix may be added, or the pattern would not match it.
    Tenant databases always contain exactly one '_' and canaries contain none, so a canary never collides
    with a tenant database."""
    return db.replace("_", "0")


def role_name(db, suffix):
    return f"r_{db}_{suffix}"


def q_user(u):
    return f"'{u}'@'%'"


def build_pool_plans(plan):
    """Group the D2 plan per pool: databases, roles (with privileges), accounts (with roles and budget)."""
    pools = {}
    for d in plan["cloud_sql_databases"].values():
        p = pools.setdefault(d["pool"], {"pool": d["pool"], "pool_project": d["pool_project"], "env": d["env"],
                                          "databases": {}, "roles": {}, "accounts": {}})
        p["databases"][d["database"]] = {"tenant": d["tenant"], "product": d["product"],
                                         "charset": d["charset"], "collation": d["collation"]}
    for u in plan["cloud_sql_iam_users"].values():
        p = pools.get(u["pool"])
        if p is None:
            raise ValueError(f"user {u['user']} on {u['pool']} but no database on that pool")
        if not USER_RE.match(u["user"]) or len(u["user"]) > 32:
            raise ValueError(f"MySQL user '{u['user']}' invalid or longer than 32 characters (M1)")
        suffix = PURPOSE_ROLE[u["purpose"]]
        roles = []
        for db in u["databases"]:
            if db not in p["databases"]:
                raise ValueError(f"{u['user']} references {db}, which is not on {u['pool']}")
            r = role_name(db, suffix)
            p["roles"][r] = {"database": db, "purpose": suffix, "privileges": ROLE_PRIVILEGES[suffix]}
            roles.append(r)
        p["accounts"][u["user"]] = {
            "sa_email": u["sa_email"], "purpose": u["purpose"], "isolation_boundary": u["isolation_boundary"],
            "databases": sorted(u["databases"]), "roles": sorted(roles),
            "max_user_connections": CONNECTION_BUDGET[(u["purpose"], u["isolation_boundary"])]}
    for p in pools.values():
        p["canaries"] = list(CANARY_STATIC) + sorted(wildcard_canary(db) for db in p["databases"])
    return dict(sorted(pools.items()))


def check_pool_plan(pp):
    """Static rules on the generated grants (fail closed before any SQL is run)."""
    errors = []
    for r, spec in pp["roles"].items():
        bad = set(spec["privileges"]) & FORBIDDEN_PRIVILEGES
        if bad:
            errors.append(f"{r}: forbidden privileges {sorted(bad)}")
        if not r.startswith(f"r_{spec['database']}_"):
            errors.append(f"{r}: role name does not carry its database")
    for a, spec in pp["accounts"].items():
        dbs = {pp["roles"][r]["database"] for r in spec["roles"]}
        if spec["isolation_boundary"] == "identity-and-database":
            tenants = {pp["databases"][d]["tenant"] for d in dbs}
            if len(tenants) != 1:
                errors.append(f"{a}: dedicated identity reaches {len(tenants)} tenants' databases")
        if any(pp["roles"][r]["purpose"] == "ddl" for r in spec["roles"]) and spec["purpose"] != "mig":
            errors.append(f"{a}: DDL role on a non-migration identity")
    return errors


def render_sql(pp):
    """Idempotent bootstrap SQL for one pool. Re-running it changes nothing."""
    out = [f"-- Generated by tools/db/grants.py – do not edit. Pool {pp['pool']} ({pp['pool_project']}).",
           "-- Runs as the bootstrap identity (cloudsqlsuperuser). IAM users already exist (Terraform google_sql_user).",
           ""]
    out.append("-- 1. tenant databases")
    for db, d in pp["databases"].items():
        out.append(f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET {d['charset']} COLLATE {d['collation']};")
    out.append("")
    out.append("-- 2. isolation-test canaries (ISO-03): static canaries + one wildcard canary per tenant database")
    for c in pp["canaries"]:
        out.append(f"CREATE DATABASE IF NOT EXISTS `{c}`;")
        out.append(f"CREATE TABLE IF NOT EXISTS `{c}`.`canary` (id INT PRIMARY KEY);")
    out.append("")
    out.append("-- 3. per-database roles; grants use the ESCAPED database name (M2)")
    for r, spec in pp["roles"].items():
        out.append(f"CREATE ROLE IF NOT EXISTS '{r}';")
        out.append(f"GRANT {', '.join(spec['privileges'])} ON `{escape_db_pattern(spec['database'])}`.* TO '{r}';")
    out.append("")
    out.append("-- 4. role membership, default roles, connection budget")
    for a, spec in pp["accounts"].items():
        tag = "  -- application-level tenant isolation (ADR-006 rev. 3)" if spec["isolation_boundary"] == "application" else ""
        out.append(f"GRANT {', '.join(repr(r) for r in spec['roles'])} TO {q_user(a)};{tag}")
        out.append(f"SET DEFAULT ROLE ALL TO {q_user(a)};")
        out.append(f"ALTER USER {q_user(a)} WITH MAX_USER_CONNECTIONS {spec['max_user_connections']};")
    out.append("")
    return "\n".join(out)


def expected_grants(pp):
    """Exact SHOW GRANTS set (MySQL 8.4 output form) for every tenant account and role on the pool.

    Formatting is the documented MySQL 8 form; T-M2 confirms it on Cloud SQL. ISO-09 compares normalised
    grants (see normalise_grant), so privilege order and quoting style do not matter."""
    exp = {}
    for r, spec in pp["roles"].items():
        exp[f"role:{r}"] = sorted([
            f"GRANT USAGE ON *.* TO `{r}`@`%`",
            f"GRANT {', '.join(spec['privileges'])} ON `{escape_db_pattern(spec['database'])}`.* TO `{r}`@`%`"])
    for a, spec in pp["accounts"].items():
        exp[f"user:{a}"] = sorted([f"GRANT USAGE ON *.* TO `{a}`@`%`",
                                   f"GRANT {','.join(f'`{r}`@`%`' for r in spec['roles'])} TO `{a}`@`%`"])
    return dict(sorted(exp.items()))


_PRIV_GRANT = re.compile(r"^GRANT (?P<privs>.+?) ON (?P<obj>\S+) TO (?P<who>\S+?)(?P<opt> WITH GRANT OPTION)?$")
_ROLE_GRANT = re.compile(r"^GRANT (?P<roles>`[^ ]+`(?:\s*,\s*`[^ ]+`)*) TO (?P<who>\S+?)(?P<opt> WITH ADMIN OPTION)?$")


def _unq(s):
    return s.replace("`", "").replace("'", "")


def normalise_grant(line):
    """SHOW GRANTS line -> comparable tuple. Raises ValueError for lines it cannot parse (treated as drift)."""
    line = line.strip().rstrip(";")
    m = _ROLE_GRANT.match(line)
    if m and " ON " not in line:
        roles = tuple(sorted(_unq(r.strip()) for r in m.group("roles").split(",")))
        return ("roles", roles, _unq(m.group("who")), bool(m.group("opt")))
    m = _PRIV_GRANT.match(line)
    if m:
        privs = tuple(sorted(p.strip().upper() for p in m.group("privs").split(",")))
        return ("privs", privs, _unq(m.group("obj")), _unq(m.group("who")), bool(m.group("opt")))
    raise ValueError(f"unparseable grant: {line}")


def isotest_impersonation(pools):
    """Resource-level IAM bindings: isotest-<tier> may mint tokens for the database-user SAs of its tier only
    (access matrix scope sa-set:db-users-<tier>). Applied by Terraform in Stage 5."""
    out = []
    for pp in pools.values():
        tier = "prd" if pp["env"] == "prd" else "nonprd"
        for a in pp["accounts"].values():
            out.append({"resource": a["sa_email"], "role": "roles/iam.serviceAccountTokenCreator",
                        "member": f"serviceAccount:isotest-{tier}@shr-cicd-{tier}.iam.gserviceaccount.com",
                        "tier": tier})
    return sorted(out, key=lambda b: b["resource"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("plan", nargs="?", default="build/identity-plan.json")
    ap.add_argument("-o", "--out", default="build/sql")
    a = ap.parse_args(argv)
    plan = json.loads(pathlib.Path(a.plan).read_text())
    pools = build_pool_plans(plan)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    errors = []
    for name, pp in pools.items():
        errors += [f"{name}: {e}" for e in check_pool_plan(pp)]
        (out / f"{name}.sql").write_text(render_sql(pp))
        (out / f"{name}.expected-grants.json").write_text(json.dumps(expected_grants(pp), indent=2) + "\n")
        (out / f"{name}.pool-plan.json").write_text(json.dumps(pp, indent=2, sort_keys=True) + "\n")
    (out / "isotest-impersonation.json").write_text(json.dumps(isotest_impersonation(pools), indent=2) + "\n")
    for e in errors:
        print("ERROR", e, file=sys.stderr)
    print(f"{len(pools)} pools, {sum(len(p['databases']) for p in pools.values())} databases, "
          f"{sum(len(p['roles']) for p in pools.values())} roles, "
          f"{sum(len(p['accounts']) for p in pools.values())} accounts -> {out}/")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
