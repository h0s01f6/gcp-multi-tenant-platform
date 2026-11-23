# Database architecture – Cloud SQL for MySQL

> **Status:** Proposed (Stage 2 final reconciliation, 2026-11-22). Supersedes every PostgreSQL-specific design in earlier Stage 2 documents.
> Decisions: ADR-011 (engine), ADR-003 rev. 3 (pooling and isolation), ADR-004 (dedicated tier), ADR-009 rev. 2 (identities and groups).
> **Nothing here has been tested in a GCP project.** "Documented" means stated in Google Cloud or MySQL documentation; items that need a test are listed in §13 with IDs (T-…).
> Review IDs introduced here: **M1–M8** (MySQL findings). Finding A3 (PostgreSQL `PUBLIC` privileges) is **superseded** – it does not apply to MySQL; MySQL's own risks are M1–M3.

---

## 1. Engine and version

| Item | Decision |
|---|---|
| Engine | **Cloud SQL for MySQL** – stakeholder preference: the team knows MySQL and can operate and defend it **[Decision, ADR-011]** |
| Major version | **MySQL 8.4** for all new pools. It is Cloud SQL's current default major version, and Google recommends accepting the default unless you need a version-specific capability. |
| Alternatives checked | **MySQL 8.0** is still supported (minor versions up to 8.0.46), but it is the older line; after a major version reaches community end-of-life, Cloud SQL moves it to extended support. **MySQL 9.7** was added to Cloud SQL in August 2026. It is too new for this design; re-evaluate when products are certified on it. |
| Edition | Prod pools: **Enterprise Plus recommended** (one maintenance event affects every tenant on a pool; Managed Connection Pooling needs Enterprise Plus). Non-prod: Enterprise. **[Q16]** |
| Version policy | One MySQL major version per product group and per non-prod pool set **[A17]**. Major upgrades are done per pool (in place or blue-green), Dev → Stage → UAT → Prod. |

---

## 2. Instance, database, privileges – the MySQL model

| Level | What it is in MySQL | What controls access |
|---|---|---|
| **Instance** (Cloud SQL instance) | One `mysqld` server with its CPU, memory, storage, flags, backups, binlog, maintenance window | **IAM** (`cloudsql.client` to reach it through a connector, `cloudsql.instanceUser` to log in with IAM), **network** (private IP in the tier's VPC), and the **existence of a MySQL account** for the identity |
| **Global privileges** (`*.*`) | Privileges that apply to the whole server: `CREATE USER`, `PROCESS`, `SHOW DATABASES`, `RELOAD`, `SYSTEM_VARIABLES_ADMIN`, … | Never granted to application or migration accounts |
| **Database** (= **schema** in MySQL) | A namespace of tables. **In MySQL "database" and "schema" are the same object.** | Database-level grants on `` `abc\_payroll`.* `` |
| **Table / column / routine** | Objects inside a database | Table- or column-level grants where a narrower role is needed (e.g. reporting user) |

**Key difference from PostgreSQL:** a MySQL connection is **not bound to one database**. A session can query `other_db.table` whenever it holds a privilege there. **Isolation between tenant databases on a shared instance is therefore enforced only by privileges**, not by a connection boundary. On the other hand, MySQL has no `PUBLIC` pseudo-role: a new account has no privileges until something is granted. Cloud SQL documents that an IAM user created without database roles gets none, while a **built-in (password) user created without roles automatically gets `cloudsqlsuperuser`**: all static privileges except `SUPER` and `FILE`.

### Can several customers' databases safely share one MySQL instance?

**Yes, if all of the following are enforced and continuously tested:**
1. Every application and migration account has privileges on **exactly one database** and **no global privileges**.
2. Application accounts are **IAM service-account users**, never built-in users (which would get `cloudsqlsuperuser`).
3. Database names in `GRANT` statements are **escaped** (`` `abc\_payroll`.* ``). In database-level grants `_` and `%` are wildcards, so an unescaped `abc_payroll` would also match a database such as `abcxpayroll` (**M2**).
4. No account receives `PROCESS` (it would reveal other tenants' running SQL in `SHOW PROCESSLIST`) or `CONNECTION_ADMIN` (it could kill other tenants' sessions) (**M2**).
5. `mandatory_roles` is empty, so no role is silently given to every account (**M2**).
6. Stored programs and views are created only with the tenant's own migration account as `DEFINER`; no tenant account holds `SET_ANY_DEFINER` / `ALLOW_NONEXISTENT_DEFINER` (8.4) or `SET_USER_ID` (8.0) (**M3**).
7. Each identity's **MySQL username is unique on the instance** (see §3, **M1**).
8. The automated isolation test (§9) passes before any workload goes live.

**Residual risks that remain on a shared instance:** shared CPU/IO/buffer pool (noisy neighbours), one maintenance window and MySQL version, one backup/PITR stream and one CMEK key per instance, and the platform bootstrap identity that can administer every tenant on the pool. Customers for whom these are unacceptable go to the dedicated tier (ADR-004).

---

## 3. Identities and MySQL accounts

### 3.1 Account types

| Account | Identity | Authentication | MySQL privileges | Where it exists |
|---|---|---|---|---|
| Application (runtime) | Workload SA `abc-payroll-prd@t-abc-prd.iam.gserviceaccount.com` | IAM database authentication (automatic, via connector) | Role `r_abc_payroll_app`: `SELECT, INSERT, UPDATE, DELETE, EXECUTE` on `` `abc\_payroll`.* `` | Only on the pool that holds `abc_payroll` for that environment |
| Migration (schema change) | SA `abc-payroll-prd-mig@t-abc-prd` | IAM database authentication | Role `r_abc_payroll_ddl`: app privileges + `CREATE, ALTER, DROP, INDEX, REFERENCES, CREATE VIEW, SHOW VIEW, TRIGGER, CREATE ROUTINE, ALTER ROUTINE, EVENT, LOCK TABLES, CREATE TEMPORARY TABLES` on `` `abc\_payroll`.* `` | Same pool; used only by migration jobs |
| Optional read-only (reporting/support) | SA `abc-payroll-prd-ro@t-abc-prd` | IAM | Role `r_abc_payroll_ro`: `SELECT` (optionally column-restricted) | Only where a product needs it |
| Platform bootstrap / DBA automation | SA `sqlboot-prd@plt-sql-prd-01` | IAM database authentication | `cloudsqlsuperuser` (Cloud SQL allows granting it to IAM users) | Every prod pool in that pool project |
| Human DBAs | People in `grp-hum-dba-prd-ro` / `grp-hum-dba-prd-admin` | **Cloud SQL IAM group authentication** (the group is added to the instance as a database user) | **Centrally approved, role-based** privileges: diagnostics read-only (`-ro`) or administrative (`-admin`, **time-bound group membership with expiry after approval** – PAM grants IAM roles, not group membership (K21)). These are platform roles across the pool, not customer-specific grants | Prod pools (≤ 3 groups per instance, limit 200) |
| `root@%` | Built-in | Password: random, stored sealed in Secret Manager in the pool project | Default all privileges except `SUPER`/`FILE` | Break-glass only; any use alerts |
| Cloud SQL system users (`cloudsqlreplica`, `cloudiamgroup`, …) | Managed by Google | – | – | Cannot be modified |

### 3.2 Naming rule forced by MySQL IAM authentication (M1 – critical)

For IAM service accounts, the MySQL username is the service account email **without the `@project-id.iam.gserviceaccount.com` suffix**, and MySQL usernames are limited to **32 characters**. The Stage 2 naming `payroll-prd@t-abc-prd` and `payroll-prd@t-xyz-prd` would therefore **both become the MySQL user `payroll-prd`** on the shared pool `sql-prd-payroll-01`. They would collide, and XYZ could end up mapped to ABC's account.

**Correction:** workload SA IDs are globally unique per customer-product-environment and fit both limits:

| Identity | SA ID pattern (≤ 30 chars, SA limit) | Example | MySQL username (≤ 32) |
|---|---|---|---|
| App | `<cust>-<product>-<env>` | `abc-payroll-prd` | `abc-payroll-prd` |
| Migration | `<cust>-<product>-<env>-mig` | `abc-payroll-prd-mig` | `abc-payroll-prd-mig` |
| Read-only | `<cust>-<product>-<env>-ro` | `abc-payroll-prd-ro` | `abc-payroll-prd-ro` |
| MySQL role | `r_<cust>_<product>_<app\|ddl\|ro>` | `r_abc_payroll_ddl` | (role, ≤ 32) |

**Length budget (corrected – review K18).** Google IAM requires a service-account ID of **6–30 characters**, lowercase letters, digits and hyphens, starting with a letter and not ending with a hyphen (regex `[a-z]([-a-z0-9]*[a-z0-9])`). The earlier text allowed a 12-character product slug, which gives 10 + 1 + 12 + 1 + 3 + 4 = **31** for the migration SA – one character too long. Corrected slug rules:

| Element | Rule | Max length |
|---|---|---|
| Customer slug | `^[a-z][a-z0-9]{2,9}$` – 3–10 chars, no hyphens | 10 |
| Product slug | `^[a-z][a-z0-9]{1,10}$` – 2–11 chars, no hyphens | 11 |
| Environment | `dev` \| `stg` \| `uat` \| `prd` | 3 |
| Suffix | none (app), `-ro` (3), `-mig` (4) | 4 |

Longest IDs: app 10 + 1 + 11 + 1 + 3 = **26**, read-only **29**, migration **30** – all within 30 characters, and as MySQL usernames within 32. The shortest possible app ID is 3 + 1 + 2 + 1 + 3 = 10, above the 6-character minimum. No hyphens are allowed inside slugs, so a name can always be split unambiguously into customer, product and environment. Role names (`r_<cust>_<product>_ddl`, max 28) also fit MySQL's 32-character limit. The rules and boundary tests are in `registry/naming-rules.md` and `scripts/validate_names.py`. Test **T-M1** confirms the username mapping in a real project.

### 3.3 How an application authenticates

1. The workload runs as its SA: Workload Identity on GKE (KSA `payroll` in `abc-payroll-prd` impersonates `abc-payroll-prd@t-abc-prd`), the service identity on Cloud Run, the attached SA on a MIG VM.
2. The Cloud SQL Auth Proxy (GKE sidecar or MIG systemd service) or a Cloud SQL language connector opens the connection with **automatic IAM database authentication**. The connector fetches a short-lived OAuth token for the SA and uses it as the password, over TLS. The account that starts the connector must be the same account that authenticates to the database.
3. IAM checks `cloudsql.client` / `cloudsql.instanceUser`, granted through the pool-project connect group **in the project IAM policy only** (mechanism 1 in the identity model §4a). That group is **never** added to the instance as a Cloud SQL database user. Test **T-G2** is mandatory before this is relied on.
4. MySQL maps the token to the account `abc-payroll-prd`. That account has only its default role `r_abc_payroll_app`.
5. No passwords exist for application or migration identities, so there is nothing to rotate or leak.

---

## 4. Roles and grants (illustrative SQL, run by the bootstrap job)

```sql
-- per tenant database (idempotent); names derived from tenant + product only
CREATE DATABASE IF NOT EXISTS `abc_payroll` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE ROLE IF NOT EXISTS 'r_abc_payroll_app', 'r_abc_payroll_ddl', 'r_abc_payroll_ro';
GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE                 ON `abc\_payroll`.* TO 'r_abc_payroll_app';
GRANT SELECT                                                  ON `abc\_payroll`.* TO 'r_abc_payroll_ro';
GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE, CREATE, ALTER, DROP, INDEX, REFERENCES,
      CREATE VIEW, SHOW VIEW, TRIGGER, CREATE ROUTINE, ALTER ROUTINE, EVENT,
      LOCK TABLES, CREATE TEMPORARY TABLES                    ON `abc\_payroll`.* TO 'r_abc_payroll_ddl';

-- IAM users are created through the Cloud SQL API (Terraform), then:
GRANT 'r_abc_payroll_app' TO 'abc-payroll-prd'@'%';
GRANT 'r_abc_payroll_ddl' TO 'abc-payroll-prd-mig'@'%';
SET DEFAULT ROLE ALL TO 'abc-payroll-prd'@'%', 'abc-payroll-prd-mig'@'%';
ALTER USER 'abc-payroll-prd'@'%' WITH MAX_USER_CONNECTIONS 20;   -- per-tenant connection budget (T-M3)
```

Rules:
- Roles are **per tenant database** (`r_<cust>_<product>_<purpose>`). Roles are instance-wide objects in MySQL, so a shared "app" role would give every tenant access to every database.
- No `WITH GRANT OPTION`, no `*.*` grants, no grants on `mysql`, `sys` or `performance_schema` to tenant roles.
- Cloud SQL can also attach database roles when the IAM user is created (`--database-roles`), which lets Terraform own both the user and its role membership. Use it where available; the job above is the fallback and the verifier.

---

## 5. Hardening baseline

**Pool level (applied when a pool instance is created and checked daily):**

| Setting | Value / rule | Why |
|---|---|---|
| `cloudsql_iam_authentication` | on | IAM logins for workloads and humans |
| SSL / connector enforcement | Connections only through Cloud SQL connectors or TLS | Encrypted, identity-bound connections |
| Network | Private IP only (private services access in the tier VPC) | No public endpoint |
| `mandatory_roles` | empty | No role silently given to all accounts (M2) |
| `local_infile` | off | Prevents client-side file loading |
| `log_bin_trust_function_creators` | off | Routines need proper privileges (M3) |
| `root@%` | random password, sealed in Secret Manager, break-glass alert | No standing admin credential in use |
| Audit | Cloud SQL MySQL audit plugin rules for DDL, `GRANT`/`REVOKE`, logins of admin accounts | Evidence for isolation and change control |
| Canary databases | `zz_canary_a`, `zz_canary_b`, plus a name that an unescaped wildcard would match | Used by the isolation test |
| Edition / HA | Prod: Enterprise Plus, HA, PITR (binary logging), backups, cross-region replica per Q10 | Shared blast radius |

**Account level:** the eight rules in §2 ("safely share").

---

## 6. Repeatable database bootstrap process

The process is idempotent and runs as `sqlboot-<tier>@plt-sql-<tier>-NN` from a Cloud Run job inside the tier's VPC. It is triggered by the pipeline, never run by hand.

```
Onboard subscription (customer, product, env):
 1. Terraform  : SAs <cust>-<product>-<env>[-mig] in t-<cust>-<tier>; add them to the pool-project connect group
 2. Terraform  : google_sql_database  <cust>_<product>  on the placed pool
 3. Terraform  : google_sql_user (CLOUD_IAM_SERVICE_ACCOUNT) for app and migration SAs
 4. Bootstrap  : CREATE ROLE / GRANT (escaped db name) / SET DEFAULT ROLE / MAX_USER_CONNECTIONS
 5. Bootstrap  : verify – SHOW GRANTS for both accounts equals the expected set exactly (drift = fail)
 6. Isolation test suite (§9) – must pass
 7. Record evidence (grants snapshot + test report) in the pipeline run and the audit bucket
 8. Only now: run migrations (migration job) and deploy the application
```

The same verify-and-test steps (5–7) also run **after any grant change**, **when a new pool is created**, and **nightly** on a rotating sample of tenants per pool.

---

## 7. Migrations and schema changes

- **Separate identity:** migrations run as `<cust>-<product>-<env>-mig`, never as the runtime identity. On GKE they run as a Helm pre-upgrade Job with its own KSA. On Cloud Run they run as a Cloud Run job. For MIG products they run as a pipeline-triggered Cloud Run job. The runtime identity cannot run DDL.
- **Tooling:** chosen per product (Flyway, Liquibase, or the framework's migrator), versioned with the application and pinned to the release.
- **Expand / contract:** each release only *adds* (columns, tables, indexes) in a backward-compatible way. Removals happen in a later release once no running version needs the old structure. This allows rollback of the application without rolling back the database.
- **MySQL DDL is not transactional:** a failed multi-statement migration can leave a partial change. Before every prod migration: an **on-demand backup**; migrations must be written as small, re-runnable steps.
- **Online DDL:** state `ALGORITHM=INSTANT` or `INPLACE` with `LOCK=NONE` explicitly so that a change which would lock or copy a large table **fails fast** instead of blocking. Large-table rebuilds are scheduled with the platform DBA team. Tools such as gh-ost or pt-online-schema-change need extra privileges and are a separate, validated runbook, not tenant self-service.
- **Shared-instance etiquette:** heavy migrations consume shared IO; prod migrations for a pool are serialised (pipeline concurrency group per pool) and preferably run in the product's change window.

---

## 8. Connection pooling (M5)

| Option | Documented facts (Cloud SQL for MySQL) | Fit |
|---|---|---|
| **Managed Connection Pooling** | The instance must be **Enterprise Plus** and on a minimum maintenance version; enabling it on an existing instance **restarts the database**; `max_pool_size` defaults to the instance's vCPU count; clients still count toward `max_connections`. The MySQL page does **not** state whether IAM database authentication or IAM group authentication works with it, and does not state whether the feature is GA. | Promising for busy prod pools, **only after test T-M5** confirms IAM authentication works through it |
| **Application-side pooling** (HikariCP, SQLAlchemy pool, Go `database/sql`…) | Always needed: the connector opens connections, the pool reuses them | **Default** – small pools per replica, sized from the connection budget |
| **External proxy (e.g. ProxySQL)** | Supports MySQL multiplexing, but would need to authenticate to Cloud SQL as every tenant's IAM identity with short-lived tokens, and adds a component per tier to run and secure | Not recommended for the initial platform |

**Recommended default:** application-side pooling plus an explicit **connection budget** per pool. The budget is enforced in three places: pool size × max replicas (HPA) or max instances (Cloud Run) in the chart and service configuration; `MAX_USER_CONNECTIONS` per tenant account (test T-M3); and alerting when a pool passes 70% of `max_connections`. Managed Connection Pooling is an **optional optimisation** for Enterprise Plus prod pools once T-M5 passes.

---

## 9. Automated cross-tenant isolation test (mandatory gate)

Runs as a pipeline job using the real identities (impersonating each SA through dedicated test permissions). Any failure **blocks** onboarding, promotion and deployment for that pool.

| ID | Check | Expected result |
|---|---|---|
| ISO-01 | `abc-payroll-prd` → `USE xyz_payroll` / `SELECT` from an `xyz_payroll` table (both on `sql-prd-payroll-01`) | Error 1044/1142 (access denied) |
| ISO-02 | `abc-payroll-prd` → `SHOW DATABASES` | Only `abc_payroll` (plus `information_schema`) is visible |
| ISO-03 | `abc-payroll-prd` → canary database whose name an unescaped `abc_payroll` grant would match | Access denied (proves wildcard escaping, M2) |
| ISO-04 | `abc-payroll-dev` → connect to any **prod** pool | Fails before MySQL: not in the prod connect group, no route from the non-prod VPC, no account on the prod pool |
| ISO-05 | `abc-payroll-prd` → admin operations: `CREATE USER`, `GRANT`, `CREATE DATABASE`, `DROP DATABASE abc_payroll`, `SET GLOBAL`, `SELECT` on `mysql.user`, `KILL` of another session | All denied |
| ISO-06 | `abc-payroll-prd` → `SHOW PROCESSLIST` while `xyz-payroll-prd` runs a query | Only its own threads visible |
| ISO-07 | `abc-payroll-prd` (runtime) → `CREATE TABLE` / `ALTER TABLE` in `abc_payroll` | Denied (DDL only via migration identity) |
| ISO-08 | `abc-payroll-prd-mig` → DDL in `xyz_payroll`; create a view with `DEFINER` set to another account | Denied |
| ISO-09 | `SHOW GRANTS` for every account on the pool equals the expected set from the registry | Exact match (no drift) |
| ISO-10 | After offboarding: login as the removed identity | Login fails; account and roles no longer exist |

**Implementation (Stage 3 D4):** `tools/db/grants.py` and `tools/db/isotest.py` (see `tools/db/README.md`). The probes are non-destructive: the `DROP` check of ISO-05 uses `DROP TABLE IF EXISTS` on a missing table in the account's own database (same `DROP` privilege, no damage if it succeeds), `SET GLOBAL` re-sets a variable to its current value, and `KILL QUERY` replaces `KILL`. ISO-09 runs inside the bootstrap job; the other probes run as `isotest-<tier>`, impersonating the tier's database-user SAs.

The four checks requested for this stage map to ISO-01 (ABC Payroll cannot access XYZ Payroll), ISO-04 (ABC Payroll Dev cannot access ABC Payroll Prod), ISO-05/07 (an application identity cannot perform administrative operations) and ISO-01/02/03 (no cross-customer access on a shared instance).

---

## 10. Backup, restore and single-tenant recovery

- Backups, binary-log PITR and replicas are **per instance**. One customer's database is recovered by cloning the pool to a temporary instance at the required time, exporting only that database (Cloud SQL export with a single `--database`), and importing it into the live pool after renaming the damaged database. Then the clone is deleted. Pool size caps (capacity model) keep the clone time within the RTO; test **T-M8** measures it.
- Prod: automated backups, PITR, an on-demand backup before every migration, backups retained in a second region, and a cross-region replica per pool if regional DR is required **[Q10]**.

---

## 11. Offboarding and emergency revocation

**Planned offboarding (customer or one product):** disable traffic → final export if the contract requires it → `REVOKE` roles, `DROP USER` (via Cloud SQL API), `DROP ROLE` → `DROP DATABASE` after the agreed hold → remove the SAs from groups and delete them → ISO-10 → evidence recorded. Pool backups keep the data until their retention expires **[Q19]**.

**Emergency revocation (suspected compromise of one identity):**
1. Lock the MySQL account immediately (`ALTER USER … ACCOUNT LOCK`, test T-M4) and kill its sessions (bootstrap identity).
2. Disable the SA (IAM). This takes effect for new tokens.
3. Remove the SA from the connect group (propagation takes minutes; step 1 is what takes effect immediately).
4. For human group access: remove from the group / end the PAM grant. Cloud SQL documents that group-membership changes take about 15 minutes to propagate, so lock the account as well where speed matters.

---

## 12. Dedicated tier (ADR-004) specifics

A dedicated customer gets its own Cloud SQL for MySQL instance (Enterprise Plus, HA) in its tenant project, its own CMEK key, its own maintenance window and its own backups. The same accounts, roles, hardening baseline and isolation test apply. ISO-01 then guards against mistakes inside the customer's own instance, for example between its products.

---

## 13. MySQL vs PostgreSQL – trade-offs of this choice

| Topic | MySQL (chosen) | PostgreSQL (previous baseline) | Consequence |
|---|---|---|---|
| Team familiarity | High (stated) | Lower | Faster, safer operations – the main reason for the choice |
| Tenant boundary inside an instance | Database = schema; **no connection boundary**; privilege-only | Database is a connection boundary | MySQL depends entirely on correct grants → the stricter test suite (§9) |
| Default privileges | No `PUBLIC`; new IAM users have nothing | `PUBLIC` has `CONNECT`/`TEMP` by default | MySQL default is safer; A3 does not apply |
| IAM username mapping | SA email truncated to the local part, 32-char limit → collisions on shared pools (M1) | Full SA name | MySQL needs globally unique SA IDs |
| Row-level security | None | Available | Shared/Cohort products on MySQL must use database-per-tenant or application-enforced filtering |
| DDL | Non-transactional; strong online (INSTANT/INPLACE) DDL | Transactional DDL | Expand/contract + pre-migration backups are mandatory |
| Per-instance limits | 50,000 tables by default (M4) | No equivalent limit used in this design | Table count per tenant schema becomes a sizing input |
| Per-account limits | `MAX_USER_CONNECTIONS` per account | Per-role connection limits | Comparable noisy-neighbour control |
| Managed Connection Pooling | Enterprise Plus; IAM support undocumented for MySQL | Enterprise Plus | Both need validation; default is app-side pooling |

---

## 14. Validation tests that need a GCP test project

| ID | What to prove |
|---|---|
| T-M1 | IAM SA → MySQL username mapping and behaviour when two SAs share a local part |
| T-M2 | Escaped database names in grants; ISO-03 canary behaviour on MySQL 8.4 |
| T-M3 | `MAX_USER_CONNECTIONS` can be set on IAM SA accounts and is enforced |
| T-M4 | `ACCOUNT LOCK` on IAM accounts blocks new IAM logins immediately |
| T-M5 | Managed Connection Pooling (MySQL, Enterprise Plus) with automatic IAM authentication via the Auth Proxy / connectors |
| T-M6 | Cloud Run → Cloud SQL with automatic IAM authentication through the chosen connector path |
| T-M7 | Performance with ~40 tenant databases × ~300 tables (table cache, dictionary memory) |
| T-M8 | Single-tenant restore time: clone + per-database export/import for a full pool |
| T-G1 – T-G4 | Group tests – see [`identity-and-groups-model.md`](identity-and-groups-model.md) |
