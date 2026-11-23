# ADR-009: Hybrid identity model – groups aggregate permissions, service accounts stay individual

- **Status:** Proposed – **revision 2** (Stage 2 final reconciliation, 2026-11-22). Revision 1: "Fleet-wide IAM grants through Google groups".
- **Review IDs:** A2, B4, B12, G1–G5, K19, K20 (wording and mechanism clarification, 2026-11-22)
- **Detail:** [`documentation/identity-and-groups-model.md`](../../documentation/identity-and-groups-model.md)

## Context
- An IAM allow policy holds at most 1,500 principals and 250 groups/domains, counting each appearance; the limit cannot be raised. Shared projects (Cloud SQL pool projects, Artifact Registry, Shared VPC hosts) would exceed it with per-SA bindings (capacity model T7).
- The stakeholder wants Google Workspace / Cloud Identity groups to simplify permission management in prod and non-prod.
- Tenant isolation must not depend on groups: ABC's and XYZ's workloads must keep separate identities and separate data access.

## Decision
1. **Hybrid model.** Groups carry only permissions that are identical for all members. **Workload groups** provide common infrastructure permissions (Cloud SQL connectivity, artifact pulls, subnet use) and **never customer-specific database privileges or data access**. **Human role groups** may carry centrally approved, role-based privileges, including DBA database roles. Individual workload SAs carry everything customer-specific, including their own MySQL roles and grants. No group may give one customer's application identity access to another customer's database.
2. **Group taxonomy:** environment tier first (no group spans prod and non-prod), then category (`hum`, `pl`, `wl`), then purpose, then scope (pool project, product or customer).
3. **Workload groups:** `grp-wl-sqlconn-<tier>-NN` (per Cloud SQL pool project: `cloudsql.client` + `cloudsql.instanceUser`), `grp-wl-ar-readers-<tier>`, `grp-wl-netusers-<tier>`.
4. **Human groups** per role and tier (operators, DBAs, security, product developers, per-customer support split `-prd`/`-nonprd` (K22), break-glass); prod write only through Privileged Access Manager.
5. **Two distinct Cloud SQL mechanisms.** (a) A group in the **project IAM policy** (`cloudsql.client` + `cloudsql.instanceUser`) – used for workload connect groups; members still log in with their **own** MySQL account and grants. (b) A group added to the **instance as an IAM database user** (IAM group authentication) – members inherit the group's database privileges; used **for human DBA groups only**, at most 3 per instance against the documented limit of **200 IAM groups per instance**. Workload SAs are never members of a type-(b) group, and `grp-wl-*` groups are never added to instances. T-G2 is a mandatory test before relying on (a).
6. **Per-customer human groups are bound inside the customer's projects.** Customer logs from shared GKE clusters are routed to the tenant project (G4), so no shared policy accumulates hundreds of customer groups.
7. Membership of `wl`/`pl` groups is automated from the tenant registry by `groups-mgr-<tier>` (group manager, not super admin); human membership comes from the IdP; nightly drift detection and quarterly review.
8. Workload Identity rule: only platform cells in `plt-gke-*`; namespace creation only by the platform pipeline.

**Clarification (Stage 3, K21):** Privileged Access Manager grants temporary IAM role bindings to the requesting principal only; it cannot add a person to a group. Time-bound DBA admin access (Cloud SQL group authentication) therefore uses **group membership with expiry** after an approval, while PAM is used for IAM-role elevation (e.g. prod support write).

## Alternatives considered
| Option | Why not chosen |
|---|---|
| Individual bindings for every SA | Exceeds IAM policy limits in shared projects |
| Groups for all access, including database privileges | Members would share data access across customers; breaks isolation |
| Sharding projects only to stay under limits | Still needed for instance limits, but alone it multiplies projects just to dodge IAM limits |

## Rationale
Shared policies stay small and constant regardless of customer count. Audits still show individual identities. Tenant isolation stays where it belongs: project, resource IAM, database privileges and network.

## Disadvantages
- Group-membership changes take time to propagate (documented about 15 minutes for Cloud SQL group authentication). Onboarding and emergency revocation must account for it, using SA disable and MySQL account lock for immediate effect.
- Group management becomes security-critical; the automation identity is privileged and audited.
- **Open technical question (T-G2):** Google's how-to describes assigning `cloudsql.instanceUser` individually for individual IAM users. If a group-inherited role does not work for them, pool projects must be sharded by SA count (fallback in the capacity model).

## Revisit when
- T-G2 fails, or Google adds per-instance IAM for Cloud SQL.
