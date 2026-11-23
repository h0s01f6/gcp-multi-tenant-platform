# ADR-008: GKE cluster per environment, sharded into cells

- **Status:** Proposed (Stage 2 review, 2026-11-22). Replaces the Stage 2 "one cluster per tier" starting point.
- **Review IDs:** A1, K9

## Context
Stage 2 started with one prod cluster and one non-prod cluster. Non-prod holds Dev, Stage and UAT, so it carries three times the namespaces of prod. The capacity model shows the non-prod cluster crossing the 1,000-namespace planning heuristic at 200 customers × 5 products (50% GKE), or at 200 × 3 if most products run on GKE. Customers' product counts vary and will grow **[A14]**.

## Decision
- One GKE Autopilot cluster **per environment**: `gke-dev-as1-01`, `gke-stg-as1-01`, `gke-uat-as1-01` (project `plt-gke-nonprd`) and `gke-prd-as1-01` (project `plt-gke-prd`).
- Each cluster is a **cell**. When a cell reaches a planning threshold, a new cell `-02` is added for that environment. Thresholds are planning assumptions to validate by load testing **[A13]**: ~1,000 tenant namespaces, ~40% of the Autopilot node limit, ~70% of the Pod IP range, or a product needing different cluster-level settings.
- Placement is per subscription and per environment, recorded in the tenant registry, with **customer affinity** (a customer's GKE products in one environment share a cell while it has capacity).
- Upgrades flow Dev → Stage → UAT → Prod (release channels or maintenance windows staggered per cluster).
- `plt-gke-*` projects contain **only platform cells** (Workload Identity identity sameness, see ADR-009 / review F5).

## Alternatives considered
| Option | Why not chosen |
|---|---|
| One non-prod cluster, shard earlier | Mixes three environments' blast radius and upgrade timing in one cluster; still needs sharding |
| Cluster per product | 15–20+ clusters per environment from day one; poor utilisation for small products |
| Cluster per customer | Rejected in ADR-001 (cost) |

## Rationale
Per-environment clusters make namespace count per cluster equal to `subscriptions × GKE share`, the same in every environment, so one sizing rule works everywhere. They also give a natural upgrade canary sequence and keep a broken Dev cluster away from UAT.

## Disadvantages
- Four clusters (plus DR) instead of two at minimum: more cluster management fees, upgrades and monitoring targets.
- Cross-cell operations (fleet rollouts, dashboards) need fleet-aware tooling.

## Revisit when
- Load tests show a different namespace or object threshold.
- Non-prod usage is so small that Dev and Stage could share a cluster again.
