# ADR-006: Dedicated, Shared and Cohort product deployment models

- **Status:** Proposed – **revision 3** (Stage 2 final reconciliation, 2026-11-22). Which products use which model is unknown (Q1); **savings are illustrative until product suitability is confirmed**.
- **Review IDs:** A7, K4, X11, C3, M-series (MySQL has no row-level security)

## Context
Different customers can run different versions of the same product **[C]**. Some products may be multi-tenant by design. Revision 2 gave Shared/Cohort deployments a home; this revision qualifies their savings and reflects the MySQL engine (ADR-011).

## Decision
Each product declares `deployment_model` in the product catalogue.

| Model | Instances per environment | Per-customer versions | Where it runs | Names | Tenant isolation lives in | Database pattern (MySQL) |
|---|---|---|---|---|---|---|
| **Dedicated** (default) | One per subscribed customer | Yes | GKE namespace in the environment's cell; Cloud Run / MIG in the **customer's** tenant project | `abc-payroll-dev`; `crm-dev` in `t-abc-nonprd` | Infrastructure (platform) | One database per customer on a pool, per-customer SA and role (ADR-003 rev. 3) |
| **Shared** | One | No – one version for all; feature flags for differences | Namespace `shr-<product>-<env>`; Cloud Run / MIG in product project `p-<product>-<env_tier>` | `shr-notify-dev`; `p-notify-nonprd` | **Application code** | **One MySQL database per tenant** on the product's own instance (MySQL has no row-level security; a shared `tenant_id` column relies entirely on application filtering and is discouraged) |
| **Cohort** | One per version cohort | Yes, per cohort | Namespace `coh-<product>-<cohort>-<env>`; Cloud Run / MIG in `p-<product>-<env_tier>` | `coh-ledger-v4-prd` | Application code | Same as Shared, per cohort |

Registry representation: Dedicated → `versions` per environment; Shared → `config` only (version in the catalogue); Cohort → `cohort` per environment (cohort → version in the catalogue).

## What the "savings" are – and are not
The ~40% reduction in infrastructure deployments in the capacity model comes from an **illustrative** 60/20/20 mix with 3 cohorts. It is not a planned saving until product teams confirm which products are multi-tenant **[Q1]**.

| Quantity | Effect of Shared/Cohort |
|---|---|
| Customer subscriptions | Unchanged |
| Infrastructure deployments | Reduced (this is the only count that drops) |
| Customer databases | Unchanged in number (database per tenant), but they move to the product's instance |
| Per-customer workload identities | **Removed** – one product identity accesses all tenants' databases |
| Application replicas | Driven by total load; only idle minimums are saved |

## Additional responsibilities for Shared/Cohort products
Tenant resolution on every request; tenant-scoped queries, caches and background jobs; mapping each tenant to its database with no cross-tenant connection reuse; per-tenant rate limiting; per-tenant export and deletion; security review and penetration test of tenant isolation before approval; cohort lifecycle management (Cohort). The platform's isolation test (ISO-01…10) cannot cover these, because the product identity legitimately reaches every tenant's database.

## Alternatives considered
- **Dedicated for all products:** simplest to govern; most expensive (especially MIG products).
- **Shared for all products:** cannot meet per-customer versions; moves isolation into every product.

## Disadvantages
- Three patterns to support; product projects (≤ 2 per Shared/Cohort product).
- Shared/Cohort customer data is isolated only by application logic and the product identity can read all tenants.

## Revisit when
- Product teams confirm which products are multi-tenant (Q1); MIG-based Dedicated deployments dominate cost.
