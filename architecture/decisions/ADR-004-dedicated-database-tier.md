# ADR-004: Dedicated database instances as an opt-in tier

- **Status:** Proposed (Stage 2 baseline; updated for Cloud SQL for MySQL in the final reconciliation, 2026-11-22; which customers qualify is an open question – Q2, Q3)
- **Date:** 2026-11-22

## Context
Some customers may be heavy users, have stricter contracts, or be regulated. Pooling (ADR-003) does not suit them.

## Decision
Offer isolation tiers selected by the `isolation_tier` field in the tenant file (renamed from `tier` in the Stage 2 review, K2):

| Tier | Database | Compute |
|---|---|---|
| Standard (default) | Database on a pooled instance | Shared cluster nodes / tenant-project Cloud Run and MIGs |
| Enhanced | **Dedicated Cloud SQL for MySQL 8.4 instance in the customer's tenant project** (Enterprise Plus, HA) | Dedicated nodes in the shared cluster (workload separation) |
| Dedicated | Dedicated MySQL instance with a customer-specific CMEK key, own maintenance window and backups; optional VPC Service Controls perimeter | Own GKE cluster in the customer's prod project |

The same Terraform modules create all tiers; moving tier = config change + one-time data migration (per-database export/import or replication-based cutover of the customer's MySQL databases). The same accounts, roles, hardening baseline and isolation test (ISO-01…10) apply on dedicated instances, where they also separate the customer's own products from each other.

Non-prod for Enhanced/Dedicated customers uses the shared tiers by default (masked data); a contract may require otherwise **[Q18]**.

## Alternatives considered
- **Dedicated for everyone:** see ADR-003 option A (cost).
- **Never dedicated:** cannot meet contracts that require independent maintenance windows, engine versions, keys or restores.

## Rationale
Pays for isolation only where a customer needs it, without a second architecture.

## Disadvantages
- Two database operating models (pooled and dedicated) to monitor and patch.
- Tier changes require a data migration with a short write freeze.
- Pricing/commercial rules for tiers must be defined by the business.

## Revisit when
- More than roughly a quarter of customers are dedicated (pooling no longer pays off; reconsider ADR-001).
- No customer ever needs it after the first year (simplify by removing the tier).
