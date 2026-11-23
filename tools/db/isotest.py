"""D4 – cross-tenant database isolation-test harness (ISO-01 … ISO-10, database architecture §9).

The harness is a mandatory pipeline gate: any FAIL or ERROR blocks onboarding, promotion and deployment for the pool.

Two identities run it (security/access-matrix.yaml):
  * probes (ISO-01..08, ISO-10 login) – isotest-<tier>@shr-cicd-<tier> impersonates each tenant/product SA and logs in
    with automatic IAM database authentication, so the probes use the REAL accounts and grants;
  * checks that read the grant tables (ISO-09, ISO-10 account check) – the pool's bootstrap identity
    sqlboot-<tier>, inside the bootstrap job (§6 step 5).
The tier boundary is preserved: isotest-nonprd cannot impersonate prod SAs, so ISO-04 is run from non-prod.

Every probe is non-destructive if isolation is broken: it targets a non-existent table, re-sets a variable to its own
value, or creates an object that the harness then removes (`cleanup`). Probes never read tenant rows.

Database access is behind a small connector interface so the logic is testable without MySQL:
    connector.connect(pool, user) -> session        raises ConnectRefused if IAM / network / account stops it
    session.execute(sql) -> list[tuple]               raises DbError(code, message)
    session.connection_id, session.close()
The production connector (Cloud SQL Python Connector + PyMySQL, enable_iam_auth=True, impersonated credentials)
is Stage 7 work; it needs packages that are not installed in this workspace.
Status: implemented + locally tested against a privilege MODEL (tests/fake_mysql.py), not against MySQL.
        Real execution = cloud tests T-M2, T-M4, T-M9, T-M10.
"""
import argparse
import json
import pathlib
import sys
from dataclasses import asdict, dataclass, field

from tools.db.grants import build_pool_plans, expected_grants, normalise_grant

# MySQL error codes that mean "not allowed" (8.4 reference).
ER_DBACCESS_DENIED = 1044      # database-level
ER_ACCESS_DENIED = 1045        # login
ER_TABLEACCESS_DENIED = 1142   # table-level command
ER_SPECIFIC_ACCESS_DENIED = 1227  # needs a global/dynamic privilege
ER_KILL_DENIED = 1095
DENIED = {ER_DBACCESS_DENIED, ER_ACCESS_DENIED, ER_TABLEACCESS_DENIED, ER_SPECIFIC_ACCESS_DENIED, ER_KILL_DENIED,
          1143, 1370, 1410}
SYSTEM_SCHEMAS_VISIBLE = {"information_schema"}   # exact visible set confirmed by T-M2 (performance_schema?)
# Accounts on a pool that are not tenant accounts (ISO-09 ignores them; anything else unexpected = drift).
PLATFORM_ACCOUNT_PREFIXES = ("root", "mysql.", "cloudsql", "sqlboot-", "grp-hum-dba-")
PROBE = "zz_iso_probe"


class DbError(Exception):
    def __init__(self, code, message=""):
        super().__init__(f"{code} {message}")
        self.code, self.message = code, message


class ConnectRefused(Exception):
    """Connection stopped before MySQL authorisation (IAM, network or no account)."""


@dataclass
class Case:
    id: str
    pool: str
    actor: str
    kind: str                 # deny | show_databases | processlist | no_connect | grants | accounts | gone
    description: str
    statement: str = ""
    target: str = ""
    expected: list = field(default_factory=list)
    cleanup: str = ""
    boundary: str = "identity-and-database"


@dataclass
class Result:
    case: Case
    outcome: str              # PASS | FAIL | ERROR
    detail: str = ""


def _app_accounts(pp, boundary=None):
    return [a for a, s in pp["accounts"].items() if s["purpose"] == "app"
            and (boundary is None or s["isolation_boundary"] == boundary)]


def generate_cases(pools, removed=(), max_targets=None):
    """Build the case list for every pool. `removed` = [(pool, user)] from the last offboarding (ISO-10)."""
    cases = []
    prd_pools = {n: p for n, p in pools.items() if p["env"] == "prd"}
    for name, pp in pools.items():
        dbs = list(pp["databases"])
        for actor, spec in pp["accounts"].items():
            own = set(spec["databases"])
            others = [d for d in dbs if d not in own][:max_targets]
            b = spec["isolation_boundary"]
            # ISO-01 – no access to another tenant's database on the same instance
            for d in others:
                cases.append(Case("ISO-01", name, actor, "deny", f"{actor} cannot use {d}", f"USE `{d}`", d,
                                  [ER_DBACCESS_DENIED], boundary=b))
            # ISO-02 – only own databases visible
            cases.append(Case("ISO-02", name, actor, "show_databases", f"{actor} sees only its databases",
                              "SHOW DATABASES", expected=sorted(own | SYSTEM_SCHEMAS_VISIBLE), boundary=b))
            # ISO-03 – canaries (incl. names an unescaped grant pattern would match) are not reachable
            for c in pp["canaries"]:
                cases.append(Case("ISO-03", name, actor, "deny", f"{actor} cannot read canary {c}",
                                  f"SELECT id FROM `{c}`.`canary` LIMIT 1", c,
                                  [ER_DBACCESS_DENIED, ER_TABLEACCESS_DENIED], boundary=b))
            mine = sorted(own)[0]
            # holder: a second account on the same pool, preferably another tenant's (ISO-05 KILL, ISO-06)
            holder = next((a for a, o in pp["accounts"].items() if a != actor and not set(o["databases"]) & own),
                          next(a for a in pp["accounts"] if a != actor))
            if spec["purpose"] == "app":
                # ISO-05 – no administrative operations (all probes harmless if they unexpectedly succeed)
                admin = [
                    ("CREATE USER", f"CREATE USER '{PROBE}'@'%' IDENTIFIED BY 'x'", f"DROP USER IF EXISTS '{PROBE}'@'%'"),
                    ("GRANT", f"GRANT SELECT ON `{mine}`.* TO '{actor}'@'%'", ""),
                    ("CREATE DATABASE", f"CREATE DATABASE `{PROBE}`", f"DROP DATABASE IF EXISTS `{PROBE}`"),
                    ("DROP (own db objects)", f"DROP TABLE IF EXISTS `{mine}`.`{PROBE}_missing`", ""),
                    ("SET GLOBAL", "SET GLOBAL max_connections = @@GLOBAL.max_connections", ""),
                    ("read mysql.user", "SELECT user FROM mysql.user LIMIT 1", ""),
                    ("KILL other session", "KILL QUERY {other_connection_id}", ""),
                ]
                for label, stmt, cleanup in admin:
                    cases.append(Case("ISO-05", name, actor, "deny", f"{actor}: {label} denied", stmt,
                                      holder if "KILL" in label else mine, sorted(DENIED), cleanup, boundary=b))
                # ISO-06 – processlist shows only own threads
                cases.append(Case("ISO-06", name, actor, "processlist", f"{actor} sees only its own threads",
                                  "SHOW PROCESSLIST", holder, boundary=b))
                # ISO-07 – runtime identity cannot run DDL in its own database
                cases.append(Case("ISO-07", name, actor, "deny", f"{actor} (runtime) cannot CREATE TABLE",
                                  f"CREATE TABLE `{mine}`.`{PROBE}` (id INT)", mine, [ER_TABLEACCESS_DENIED],
                                  f"DROP TABLE IF EXISTS `{mine}`.`{PROBE}`", boundary=b))
            if spec["purpose"] == "mig":
                # ISO-08 – migration identity: no DDL elsewhere, no foreign DEFINER
                for d in others:
                    cases.append(Case("ISO-08", name, actor, "deny", f"{actor} cannot run DDL in {d}",
                                      f"CREATE TABLE `{d}`.`{PROBE}` (id INT)", d, [ER_TABLEACCESS_DENIED, ER_DBACCESS_DENIED],
                                      f"DROP TABLE IF EXISTS `{d}`.`{PROBE}`", boundary=b))
                victim = next((a for a in pp["accounts"] if a != actor), "root")
                cases.append(Case("ISO-08", name, actor, "deny", f"{actor} cannot create a view with DEFINER {victim}",
                                  f"CREATE DEFINER=`{victim}`@`%` VIEW `{mine}`.`{PROBE}_v` AS SELECT 1",
                                  mine, [ER_SPECIFIC_ACCESS_DENIED], f"DROP VIEW IF EXISTS `{mine}`.`{PROBE}_v`", boundary=b))
            # ISO-09 – grants equal the registry-derived set (run by the bootstrap identity)
            cases.append(Case("ISO-09", name, actor, "grants", f"SHOW GRANTS for {actor} matches the registry",
                              f"SHOW GRANTS FOR '{actor}'@'%'", expected=expected_grants(pp)[f"user:{actor}"], boundary=b))
        for role in pp["roles"]:
            cases.append(Case("ISO-09", name, role, "grants", f"SHOW GRANTS for role {role} matches the registry",
                              f"SHOW GRANTS FOR '{role}'@'%'", expected=expected_grants(pp)[f"role:{role}"]))
        cases.append(Case("ISO-09", name, "*", "accounts", "no unexpected accounts or roles on the pool",
                          "SELECT user FROM mysql.user", expected=sorted(list(pp["accounts"]) + list(pp["roles"]))))
        # ISO-04 – a non-prod identity cannot reach a prod pool (stops before MySQL)
        if pp["env"] != "prd":
            for actor in _app_accounts(pp):
                product = pp["databases"][pp["accounts"][actor]["databases"][0]]["product"]
                target = next((n for n, p in prd_pools.items()
                               if any(d["product"] == product for d in p["databases"].values())),
                              next(iter(prd_pools), None))
                if target:
                    cases.append(Case("ISO-04", target, actor, "no_connect",
                                      f"{actor} ({pp['env']}) cannot connect to prod pool {target}", target=target))
    # ISO-10 – removed identities can no longer log in, and their account is gone
    for pool, user in removed:
        cases.append(Case("ISO-10", pool, user, "gone", f"offboarded {user} cannot log in to {pool}", target=pool))
    return cases


def for_tier(cases, pools, tier):
    """Cases one tier's harness runs. ISO-04 runs from non-prod (it targets a prod pool with a non-prod identity)."""
    def t(pool):
        return "prd" if pools[pool]["env"] == "prd" else "nonprd"
    if tier == "nonprd":
        return [c for c in cases if c.id == "ISO-04" or (c.pool in pools and t(c.pool) == "nonprd")]
    return [c for c in cases if c.id != "ISO-04" and c.pool in pools and t(c.pool) == "prd"]


def _deny(session, case, other_id):
    stmt = case.statement.replace("{other_connection_id}", str(other_id))
    try:
        session.execute(stmt)
    except DbError as e:
        if e.code in case.expected:
            return "PASS", f"denied ({e.code})"
        return "ERROR", f"unexpected error {e.code} {e.message}"
    return "FAIL", "statement SUCCEEDED – isolation broken"


def run(cases, connector, admin_connector=None):
    """Execute cases. connector: impersonating probe connector; admin_connector: bootstrap identity (ISO-09/10)."""
    results = []
    sessions = {}

    def sess(pool, user):
        if (pool, user) not in sessions:
            sessions[(pool, user)] = connector.connect(pool, user)
        return sessions[(pool, user)]

    for c in cases:
        try:
            if c.kind in ("deny", "show_databases", "processlist"):
                s = sess(c.pool, c.actor)
                holder = sess(c.pool, c.target) if (c.kind == "processlist" or "{other" in c.statement) else None
                if c.kind == "deny":
                    outcome, detail = _deny(s, c, holder.connection_id if holder else 0)
                    if outcome == "FAIL" and c.cleanup and admin_connector:
                        admin_connector.connect(c.pool, "sqlboot").execute(c.cleanup)
                        detail += f"; cleaned up with: {c.cleanup}"
                elif c.kind == "show_databases":
                    seen = {r[0] for r in s.execute(c.statement)}
                    extra = seen - set(c.expected)
                    outcome, detail = ("PASS", f"visible: {sorted(seen)}") if not extra else \
                        ("FAIL", f"also visible: {sorted(extra)}")
                else:
                    users = {r[1] for r in s.execute(c.statement)}
                    outcome, detail = ("PASS", "own threads only") if users <= {c.actor} else \
                        ("FAIL", f"threads of {sorted(users - {c.actor})} visible")
            elif c.kind == "no_connect":
                try:
                    connector.connect(c.target, c.actor).close()
                    outcome, detail = "FAIL", "connection SUCCEEDED across tiers"
                except ConnectRefused as e:
                    outcome, detail = "PASS", f"refused before MySQL: {e}"
                except DbError as e:
                    # Reaching MySQL at all means the IAM/network tier boundary did not hold (§9: "fails before MySQL")
                    outcome, detail = "FAIL", f"reached MySQL on a prod pool (error {e.code}); tier boundary not enforced"
            elif c.kind in ("grants", "accounts", "gone"):
                if admin_connector is None:
                    outcome, detail = "ERROR", "bootstrap identity not available for this check"
                else:
                    a = admin_connector.connect(c.pool, "sqlboot")
                    if c.kind == "grants":
                        got = {normalise_grant(r[0]) for r in a.execute(c.statement)}
                        want = {normalise_grant(g) for g in c.expected}
                        outcome, detail = ("PASS", "exact match") if got == want else \
                            ("FAIL", f"unexpected: {sorted(map(str, got - want))}; missing: {sorted(map(str, want - got))}")
                    elif c.kind == "accounts":
                        got = {r[0] for r in a.execute(c.statement)
                               if not r[0].startswith(PLATFORM_ACCOUNT_PREFIXES)}
                        extra, missing = got - set(c.expected), set(c.expected) - got
                        outcome, detail = ("PASS", f"{len(got)} tenant accounts/roles") if not (extra or missing) else \
                            ("FAIL", f"unexpected: {sorted(extra)}; missing: {sorted(missing)}")
                    else:
                        present = any(r[0] == c.actor for r in a.execute("SELECT user FROM mysql.user"))
                        try:
                            connector.connect(c.pool, c.actor).close()
                            login = "succeeded"
                        except (ConnectRefused, DbError):
                            login = "refused"
                        outcome = "PASS" if (not present and login == "refused") else "FAIL"
                        detail = f"account present={present}, login {login}"
        except ConnectRefused as e:
            outcome, detail = "ERROR", f"probe identity could not connect: {e}"
        except DbError as e:
            outcome, detail = "ERROR", f"{e.code} {e.message}"
        results.append(Result(c, outcome, detail))
    for s in sessions.values():
        s.close()
    return results


def report(results):
    by = {}
    for r in results:
        k = (r.case.id, r.outcome)
        by[k] = by.get(k, 0) + 1
    failed = [r for r in results if r.outcome != "PASS"]
    return {"total": len(results), "passed": len(results) - len(failed), "gate": "PASS" if not failed else "FAIL",
            "by_check": {f"{i}/{o}": n for (i, o), n in sorted(by.items())},
            "application_boundary_note": "Shared/Cohort identities reach every served tenant database by design "
                                         "(ADR-006 rev. 3); tenant separation between those databases is the "
                                         "application's responsibility and is not proven by this suite.",
            "failures": [{**asdict(r.case), "outcome": r.outcome, "detail": r.detail} for r in failed]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="List the isolation cases for a plan (execution needs a connector).")
    ap.add_argument("plan", nargs="?", default="build/identity-plan.json")
    ap.add_argument("-o", "--out", default="build/isotest-cases.json")
    a = ap.parse_args(argv)
    pools = build_pool_plans(json.loads(pathlib.Path(a.plan).read_text()))
    cases = generate_cases(pools)
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.out).write_text(json.dumps([asdict(c) for c in cases], indent=1) + "\n")
    counts = {}
    for c in cases:
        counts[c.id] = counts.get(c.id, 0) + 1
    print(f"{len(cases)} cases over {len(pools)} pools: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
