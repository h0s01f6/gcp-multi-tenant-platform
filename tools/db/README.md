# D4 – MySQL grants and the isolation-test harness

Status: **implemented and locally tested** (generation logic and a privilege model). **Not executed against MySQL / Cloud SQL.** Cloud tests: T-M2, T-M3, T-M4, T-M9, T-M10.

## Pipeline position (database architecture §6)

```
D1 registry ─► D2 identity plan ─► grants.py ─► <pool>.sql ─────────────► bootstrap job (sqlboot-<tier>), step 4
                                             ├► <pool>.expected-grants.json ─► ISO-09 drift check, step 5
                                             └► isotest-impersonation.json ─► Terraform (Stage 5)
                                   isotest.py ─► ISO-01..10 gate, step 6 (blocks onboarding / promotion / deploy)
```

```bash
python3 -m tools.identity.derive registry -o build/identity-plan.json
python3 -m tools.db.grants build/identity-plan.json -o build/sql      # 13 pools, 24 DBs, 56 roles, 56 accounts
python3 -m tools.db.isotest build/identity-plan.json                   # lists the cases (847 for the example)
python3 -m pytest -q tests/test_db_grants.py tests/test_db_isotest.py
```

## Grant generation (`grants.py`)

| Rule | How |
|---|---|
| One database per customer-product | `CREATE DATABASE IF NOT EXISTS <tenant>_<product>` (utf8mb4) |
| Roles per database and purpose | `r_<tenant>_<product>_app` (DML + EXECUTE), `_ddl` (migration identity only), `_ro` (SELECT) |
| Escaped grant pattern (M2) | `` ON `abc\_payroll`.* ``; the unescaped form is never emitted (test) |
| No global privileges | never `*.*`, `ALL`, `GRANT OPTION`, `PROCESS`, `SUPER`, `CREATE USER`, `SET_ANY_DEFINER` … (static check before SQL) |
| Dedicated identity = one tenant | static check: a Dedicated account's roles cover exactly one tenant's database |
| Shared/Cohort identity | role on every **served** tenant database, marked `application-level tenant isolation` (ADR-006 rev. 3) |
| Connection budget | `MAX_USER_CONNECTIONS` per account (representative: app 20, mig 2, ro 5, shared app 60) – T-M3 |
| Idempotent | only `IF NOT EXISTS` / `GRANT` / `SET DEFAULT ROLE` / `ALTER USER`; no `DROP`, `REVOKE`, `CREATE USER` |
| Users | created by Terraform (`google_sql_user`, `CLOUD_IAM_SERVICE_ACCOUNT`), not by this SQL |
| Canaries (ISO-03) | `zz_canary_a/b` + one per tenant database whose name the **unescaped** pattern would match (`abc0payroll`) |

Drift is never repaired silently: ISO-09 fails, and the fix is a reviewed change.

## Isolation-test harness (`isotest.py`)

| Check | Probe (non-destructive) | Pass when |
|---|---|---|
| ISO-01 | `USE` every other tenant database on the pool | 1044 |
| ISO-02 | `SHOW DATABASES` | only own databases + `information_schema` |
| ISO-03 | `SELECT` from every canary | 1044 / 1142 |
| ISO-04 | non-prod identity connects to the prod pool of the same product | refused **before MySQL** (reaching MySQL at all = FAIL) |
| ISO-05 | `CREATE USER`, `GRANT`, `CREATE DATABASE`, `DROP TABLE IF EXISTS` (missing table), `SET GLOBAL x = @@x`, read `mysql.user`, `KILL QUERY` of another tenant's session | denied |
| ISO-06 | `SHOW PROCESSLIST` while another tenant is connected | own threads only |
| ISO-07 | runtime identity `CREATE TABLE` in its own database | 1142 |
| ISO-08 | migration identity DDL in other databases; view with a foreign `DEFINER` | denied |
| ISO-09 | `SHOW GRANTS` for every account and role; account list | exact match with the registry (normalised) |
| ISO-10 | removed identity logs in; account still listed | login refused and account gone |

If a probe unexpectedly succeeds, the harness records FAIL and removes what it created (`cleanup`, via the bootstrap identity). Probes never read tenant rows.

**Who runs it.** ISO-01…08 and the ISO-10 login: `isotest-<tier>@shr-cicd-<tier>`, which impersonates the database-user SAs of its own tier only (resource-level `roles/iam.serviceAccountTokenCreator`, access matrix scope `sa-set:db-users-<tier>`). ISO-09 and the ISO-10 account check: the pool's bootstrap identity inside the bootstrap job. `for_tier()` splits the cases so each tier's runner stays in its tier; ISO-04 runs from non-prod.

**Shared/Cohort.** The suite proves that a product identity cannot leave its served tenants' databases. It does **not** prove separation between those tenants – that boundary is the application's (ADR-006 rev. 3); the report says so.

## Local testing – what it does and does not prove

`tests/fake_mysql.py` is a **privilege model**, not MySQL: it executes the generated SQL and the probes using MySQL's grant-pattern matching (`_`/`%` wildcards, `\_` escapes), role resolution and the specific error codes. The tests show that the generated grants pass all ten checks in the model and that each injected defect is caught: unescaped grant (ISO-03 + ISO-09), cross-tenant role (ISO-01/02/09), global privileges (ISO-05/06), runtime DDL (ISO-07), foreign DEFINER (ISO-08), missing tier boundary (ISO-04), leftover account (ISO-09), offboarding (ISO-10).

Still to confirm on Cloud SQL: SHOW GRANTS output format and visible system schemas (T-M2/T-M9), error codes per probe (T-M9), `MAX_USER_CONNECTIONS` and `ACCOUNT LOCK` on IAM accounts (T-M3/T-M4), impersonated IAM database login through the connector (T-M10). The production connector (Cloud SQL Python Connector + PyMySQL) is Stage 7; the packages are not installed in this workspace.
