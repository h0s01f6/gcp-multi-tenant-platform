# ADR-001: Hybrid project model

- **Status:** Proposed (Stage 2 baseline – not yet confirmed by the company)
- **Date:** 2026-11-22

## Context
200+ customers, 15–20 products, four environments, ~2,400 product deployments today and ~6,000 at 500 customers **[C + estimate]**. Customer data must be isolated **[C]**. Running a GKE cluster or database server per deployment would be very expensive; putting everything in a few shared projects makes IAM the only barrier between customers.

## Decision
Separate the **data and identity boundary** from the **compute boundary**:
- Each customer gets its own GCP projects (see ADR-007) holding its service accounts, buckets, secrets, KMS keys, Cloud Run services, MIGs and (dedicated tier) databases/clusters.
- Expensive runtimes are pooled in platform projects: GKE clusters (namespace per customer-product-env) and Cloud SQL instances (database per customer-product, ADR-003).
- Workloads on pooled runtimes act as the customer's own service account (Workload Identity / IAM DB auth), so data access still crosses a customer-owned boundary.
- Customers can be moved to Enhanced or Dedicated isolation tiers through configuration.

## Alternatives considered
| Option | Why not chosen |
|---|---|
| Project (and runtime) per customer × environment | Strongest isolation, but ~800 clusters/instances to run and pay for; most capacity idle |
| Project per customer × environment × product | ~2,400 projects; no extra isolation benefit for the cost |
| Fully shared projects, logical isolation only | Lowest cost, but one IAM/RBAC mistake exposes other customers; cost allocation and blast radius are poor |

## Rationale
Projects are free and are the strongest cheap boundary, so they are used for everything customer-owned. Clusters and database servers are expensive, so they are pooled with logical isolation and an upgrade path to dedicated.

## Disadvantages
- Two isolation models to explain and audit (project-level for tenant resources, logical for pooled runtimes).
- Pooled Cloud SQL data lives in platform projects, not tenant projects (database-level isolation only).
- Cross-project IAM wiring is more complex than a single shared project; requires a solid project factory.

## Revisit when
- Regulation or contracts require infrastructure isolation for most customers (move toward Option 1).
- The number of dedicated-tier customers grows so large that pooling saves little.
- Products become truly multi-tenant (ADR-006 Shared model), reducing the number of deployments.
