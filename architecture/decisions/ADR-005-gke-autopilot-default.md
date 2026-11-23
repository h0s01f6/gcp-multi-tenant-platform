# ADR-005: GKE Autopilot as the default cluster mode

- **Status:** Proposed (changed from "Standard" in Stage 1; needs confirmation of agent/tool support – Q6)
- **Date:** 2026-11-22

## Context
The assignment prefers managed services that reduce operational effort **[C]**. Stage 1 leaned toward Standard because per-tier node pools were part of the isolation story.

## Decision
Shared clusters use **GKE Autopilot** (regional by default). Node-level isolation for Enhanced-tier customers uses Autopilot **workload separation** (tolerations + node selectors). GKE Standard remains the fallback for workloads Autopilot does not allow.

## Alternatives considered
| Option | Pros | Cons |
|---|---|---|
| GKE Standard | Full node control, any DaemonSet/privileged workload, custom node images | Team manages node pools, sizing, upgrades and hardening; pays for unused node capacity |
| Mixed (Autopilot non-prod, Standard prod) | Cheap non-prod | Two operating models; non-prod no longer tests prod behaviour |

## Rationale
Autopilot removes node management, applies hardened defaults, bills per pod request (maps cost to tenants naturally, cheap idle non-prod and cheap pilot-light DR cluster), and still supports node separation.

## Disadvantages
- Restrictions on privileged pods, some DaemonSets and host access; some security/monitoring agents need to be on Google's allowlist.
- Pods using workload separation have higher minimum resource requests (cost for the Enhanced tier).
- Less control over node machine types (compute classes help).
- Autopilot cluster size limit (5,000 nodes) is lower than Standard's – not a constraint at the planned cell size (cluster topology and cells: ADR-008).
- Policy Controller / Gatekeeper support and licensing on Autopilot must be validated (review item B11).

## Revisit when
- A required agent or product workload cannot run on Autopilot.
- Cost analysis shows consistently high, steady utilisation where Standard bin-packing is cheaper.
