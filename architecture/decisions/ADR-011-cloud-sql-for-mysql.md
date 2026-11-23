# ADR-011: Cloud SQL for MySQL 8.4 as the default relational database

- **Status:** Accepted as a design decision (stakeholder preference, Stage 2 final reconciliation, 2026-11-22). Supersedes assumption A5 ("PostgreSQL").
- **Review IDs:** M1–M8

## Context
Stage 1b–2 assumed Cloud SQL for PostgreSQL. The architect responsible for the platform has asked for MySQL. The team knows MySQL well, and operational confidence is a legitimate architectural driver for a shared database fleet of tens to hundreds of instances. The assignment does not name a database engine **[C: none]**.

## Decision
- **Cloud SQL for MySQL, major version 8.4** (Cloud SQL's current default) for all new pools and dedicated instances.
- Prod pools on **Enterprise Plus** (recommended, **[Q16]**), non-prod on Enterprise.
- Database-per-customer-product on pooled instances (ADR-003 rev. 3), with MySQL-specific isolation controls and a mandatory isolation test ([`database-architecture-mysql.md`](../../documentation/database-architecture-mysql.md)).

## Alternatives considered
| Option | Why not chosen |
|---|---|
| Cloud SQL for PostgreSQL | Technically strong (database = connection boundary, row-level security, transactional DDL), but not the team's strength. Its advantages are offset by MySQL's safer default privilege model and compensated by the isolation test |
| MySQL 8.0 | Older line; heading to extended support after community end-of-life; no reason to start new pools on it |
| MySQL 9.7 | Added to Cloud SQL in August 2026; too new to standardise on before product certification |
| AlloyDB / Spanner | Different cost and operating models; no stated need |

## Consequences
- Tenant isolation inside a shared instance is **privilege-only** (no connection boundary) → hardening baseline + isolation test ISO-01…10 are mandatory.
- IAM usernames are the SA local part (≤ 32 chars) → **globally unique workload SA IDs** `<cust>-<product>-<env>` (M1).
- No row-level security → Shared/Cohort products use database-per-tenant or application-enforced filtering (ADR-006 rev. 3).
- Non-transactional DDL → expand/contract migrations and pre-migration backups.
- 50,000-table default limit per instance becomes a pool-sizing input (M4).

## Revisit when
- A product needs PostgreSQL-only capabilities (it could get a PostgreSQL pool as an exception, with its own ADR).
- MySQL 9.x becomes the Cloud SQL default and products are certified on it.
