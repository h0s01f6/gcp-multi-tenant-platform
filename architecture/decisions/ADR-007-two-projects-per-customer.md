# ADR-007: Two projects per customer (prd and nonprd)

- **Status:** Proposed (Stage 2 baseline; UAT placement depends on Q5)
- **Date:** 2026-11-22

## Context
Each customer has Dev, Stage, UAT and Prod **[C]**. Production must be isolated from non-production **[C]**. Projects are free but each adds IAM bindings, quota and monitoring surface.

## Decision
- `t-<cust>-prd` holds Production.
- `t-<cust>-nonprd` holds Dev, Stage and UAT, separated inside the project by **resource naming, per-environment service accounts, and resource-level IAM** (bucket, secret, Cloud Run service), never broad project-level roles for humans.

## Alternatives considered
| Option | Projects at 200 / 500 customers | Notes |
|---|---|---|
| One project per environment | 800 / 2,000 | Hard boundary between Dev, Stage and UAT; more quota requests, more attachments per Shared VPC host, larger metrics scopes |
| Three projects: prd, uat, dev-stg | 600 / 1,500 | Good fit if UAT is contractually customer-facing or uses more sensitive data |
| One project for all environments | 200 / 500 | Violates prod/non-prod isolation – rejected |

## Rationale
The boundary that matters most (prod vs non-prod) is a project boundary. Between Dev, Stage and UAT, the data is synthetic or masked and changes go only through CI, so resource-level separation is sufficient and halves the project count compared with one-per-environment.

## Disadvantages
- Dev, Stage and UAT share project-level quotas (a runaway Dev load test can consume UAT's quota).
- A mistakenly broad project-level role would span three environments – mitigated by policy (no human project-level write roles) and detection.

Note (Stage 2 review): Dev, Stage and UAT now run on separate GKE clusters (ADR-008) and separate SQL pools, so the shared non-prod *project* is the only remaining shared boundary between those environments.

## Revisit when
- UAT needs real production data or a contractual separation (move to three projects, or put UAT in the prod tier).
- Quota contention between environments is observed.
