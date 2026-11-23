# ADR-003: Pooled Cloud SQL for MySQL with a separate database per customer-product

- **Status:** Proposed – **revision 3** (Stage 2 final reconciliation, 2026-11-22). Engine changed to MySQL (ADR-011). Pooled vs dedicated for prod still needs company confirmation (Q3); pool edition needs a decision (Q16).
- **Review IDs:** A1, A2, A4, C1, M1–M8. **A3 (PostgreSQL `PUBLIC` privileges) is superseded** – it does not apply to MySQL.
- **Detail:** [`documentation/database-architecture-mysql.md`](../../documentation/database-architecture-mysql.md)

## Context
Products need relational databases (every subscription assumed to need one, A16 – unconfirmed; the capacity model shows the 60% case). One instance per customer-environment would be ~800 instances at 200 customers. Revision 2 assumed PostgreSQL; this revision reassesses every database-specific decision for MySQL.

## Decision
1. **Pools per environment.** Non-prod: `sql-dev-NN`, `sql-stg-NN`, `sql-uat-NN`, shared by products with the same MySQL major version (A17). Prod: pools per **product group**, split per product by the rule in the capacity model (≥ 50% of a pool, different version/window, > 50% of a pool's load, or contract).
2. **One MySQL database per customer-product** on its pool (`abc_payroll`). In MySQL a database *is* a schema, so "database-per-tenant" and "schema-per-tenant" are the same design. Isolation is enforced by privileges only.
3. **Accounts:** IAM service-account users only for workloads – a runtime account (`abc-payroll-prd`) and a migration account (`abc-payroll-prd-mig`). Each has a **per-database role** (`r_abc_payroll_app`, `r_abc_payroll_ddl`) with grants on the **escaped** database name only. No global privileges, no `PROCESS`, no `GRANT OPTION`, no `cloudsqlsuperuser`. Built-in users are never used by applications (they receive `cloudsqlsuperuser` automatically).
4. **Workload SA IDs are unique per customer-product-environment** (`<cust>-<product>-<env>`, `-ro`, `-mig`), because the MySQL username is the SA local part (M1). Customer slug ≤ 10 and product slug ≤ 11 characters keep the longest (migration) ID at the 30-character IAM limit (K18, `registry/naming-rules.md`).
5. **Hardening baseline** per pool (IAM auth on, connectors/TLS only, private IP, `mandatory_roles` empty, `local_infile` off, sealed `root`, audit plugin, canary databases) and the **mandatory isolation test ISO-01…10** on every onboarding, grant change, new pool and nightly sample.
6. **Platform bootstrap identity** `sqlboot-<tier>@plt-sql-<tier>-NN` (IAM user with `cloudsqlsuperuser`) runs grants and tests; it is separate from every application identity.
7. **IAM:** connect permissions via the pool-project connect group **in the project IAM policy** (ADR-009 rev. 2, mechanism 1; T-G2 mandatory); per-tenant authorisation only inside MySQL. Only human DBA groups are added to instances as IAM group database users (≤ 3 of the 200 allowed per instance).
8. **Pool projects sharded** (`plt-sql-prd-NN`, planning ceiling 100 instances, read replicas included).
9. **Capacity:** tenants per pool = tightest of tenant-count cap, connection budget, storage/restore size with growth, and the 50,000-table limit (capacity model T3).
10. **Connections:** application-side pooling + per-pool connection budget + per-account `MAX_USER_CONNECTIONS`. Managed Connection Pooling (Enterprise Plus) is optional after test T-M5.
11. **Migrations:** separate migration identity, expand/contract, explicit online-DDL algorithms, on-demand backup before prod migrations, serialised per pool.

## Alternatives considered
| Option | Why not chosen as default |
|---|---|
| A. Dedicated instance per customer | Highest cost and operations; opt-in tier (ADR-004) |
| Shared accounts / shared role across tenants | Would give every tenant access to every database on the pool |
| One instance per environment for all products | Blast radius = every customer and product; table and connection limits |
| PostgreSQL pools | See ADR-011 |

## Disadvantages
- Isolation on pooled instances is privilege-only and depends on the baseline being applied and tested every time.
- Restore/PITR is instance-level; single-tenant recovery = clone + per-database export/import.
- Shared CPU/IO, maintenance window, version, backups and CMEK key per pool.
- Pooled backups keep an offboarded tenant's data until retention expires (Q19).

## Revisit when
- Contracts require independent RTO/RPO, maintenance, version or key → dedicated tier.
- Real table counts or DB sizes (Q22) make pools very small.
- Test T-G2 fails (group-inherited `cloudsql.instanceUser`) → pool projects sharded by SA count.
