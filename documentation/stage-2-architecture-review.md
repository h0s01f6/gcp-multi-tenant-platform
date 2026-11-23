# Stage 2 architecture review

> **Date:** 2026-11-22 · **Scope:** all Stage 2 deliverables (architecture document, 12 diagrams, ADR-001…007, assumptions register, resource mapping, workflows) checked against the original assignment.
> **Method:** recomputed capacity across variable subscription scenarios; checked each GCP mechanism against current Google Cloud documentation (quotas and feature pages, Nov 2026); traced every customer-to-customer and prod/non-prod path; cross-checked names and environments across all artifacts.
> Tags: **[C]** confirmed requirement · **[A]** assumption · **[R]** recommendation · **[Q]** open question.
> Nothing was deployed; "feasible" below means *documented as supported*, not *tested*.

> **Reconciliation note (2026-11-22):** the database engine was later changed to **Cloud SQL for MySQL 8.4** (ADR-011). Findings that assumed PostgreSQL are kept below for traceability but are **superseded**: A3, X1, F6, and the PostgreSQL parts of A4 and F7 are replaced by M1–M8. B5 (log views) is replaced by G4. See the addendum at the end of this document.

---

## 1. Scalability (summary – full model in [`capacity-model.md`](capacity-model.md))

| Finding | Evidence | Verdict |
|---|---|---|
| Tenant projects = 2 × customers regardless of products subscribed | Model T4 | ✅ Holds. Adding a product never needs a new project |
| One shared non-prod GKE cluster | Non-prod holds 3× the namespaces of prod; crosses the 1,000-namespace heuristic at 200 × 5 products (50% GKE) or 200 × 3 (≈100% GKE) | ❌ Inconsistent with the stated heuristic → **A1** |
| Cloud SQL estimates "15–25 at 200 customers" | Per-product prod pools set a floor of ~20 prod instances + DR replicas even at 1 product/customer; total 46–820 across scenarios | ❌ Understated → **A1** |
| Project-level Cloud SQL IAM grants per workload SA | 2 appearances per SA; `plt-sql-nonprd` exceeds 1,500 principals at 200 × 3 | ❌ Not feasible → **A2** |
| One metrics scope per tier | 375-project guidance exceeded at 500 customers | ⚠ Shard at growth → B6 |
| CI/CD fleet operations | Up to 133 h to redeploy everything at 20 parallel jobs (500 × 20) | ⚠ Per-product waves + higher parallelism → B9 |
| MIG Dedicated deployments | ≥4,500 VMs minimum at 500 × 10 before load | ⚠ Cost risk → B10 |

---

## 2. GCP technical feasibility

| # | Area | Stage 2 assumption | Review finding | Verdict |
|---|---|---|---|---|
| F1 | Shared VPC | Two host projects; shard hosts later (`net-host-prd-02`) | Host/service model is correct. A per-host service-project quota exists (value must be read in the console; not confirmed from public docs). **Sharding a host is not free:** a second host is a second VPC, so its tenants cannot reach GKE cells and SQL pools in the first VPC without extra connectivity. | ⚠ Validate quota value before Phase 1; if it binds, shard by **cell** (VPC + clusters + pools + tenants together) → B2 |
| F2 | Cross-project LB backends (Cloud Run, MIG) | URL map in `plt-ingress-*`, backend services in tenant projects | Supported for global external ALBs ("cross-project service referencing"); the deployer needs the load-balancer service-user role on tenant backend services. URL maps are limited by size (1 MB per map) and per-project quota units. | ✅ Feasible; one URL map per product per environment, split by customer range if quota units approach the limit → B7 |
| F3 | Cloud Run networking | Direct VPC egress into shared subnet; "Cloud NGFW rules per workload tag" | Supported in Shared VPC (Cloud Run service agent needs Network User on the subnet). IP use ≈ 2 per instance → large subnet needed. Firewall rules **cannot use Resource Manager (secure) tags on Cloud Run**; network tags only. Cloud Run services accept no direct VPC ingress (good for isolation). | ⚠ Wording fixed in diagram 11; subnet sizing in Stage 4 → B8 |
| F4 | GKE Autopilot | Regional, 5,000 nodes, workload separation, NetworkPolicy | All documented. Workload separation raises minimum Pod requests. NetworkPolicy is enforced by Dataplane V2. Policy Controller/Gatekeeper on Autopilot and its licensing need validation. | ✅ with validation item → B11 |
| F5 | Workload Identity | KSA in `plt-gke-*` impersonates GSA in tenant project | Supported cross-project. **Identity sameness:** the same namespace + KSA name in any cluster of the same project gets the same identity. Safe only if `plt-gke-*` projects contain platform cells only and namespace creation is restricted. | ⚠ Design rule added → B12 |
| F6 | Cloud SQL IAM DB auth | Workload SA logs in as IAM user, `CONNECT` on own DB only | IAM DB auth works with private IP. Cloud SQL IAM roles are **project-level** (no per-instance bindings), hence A2. IAM users don't get `cloudsqlsuperuser` (built-in users do). **PostgreSQL grants `CONNECT` and `TEMP` on every database to `PUBLIC` by default**, so "own DB only" is false unless revoked. | ❌ → **A2, A3** |
| F7 | Connection pooling | "PgBouncer or Cloud SQL managed pooling" | Managed Connection Pooling requires **Cloud SQL Enterprise Plus**. Current docs list IAM options per port, but an earlier version of the docs excluded IAM users. A self-run PgBouncer has to hold short-lived IAM tokens for every tenant user, which is non-trivial. | ❌ Edition dependency missing → **A4** |
| F8 | Tenant-specific recovery | PITR clone → copy one database back | Correct: restore/PITR is instance-level and creates a new instance. RTO grows with total pool size (whole instance is cloned). | ✅ with pool size cap (storage, not just tenant count) → B13 |
| F9 | Prod/non-prod CI separation | Separate runner pools and deployer SAs | **Enforceable** only if all of these hold: WIF provider condition on repository ID; prod SA impersonation bound to `environment=prd` **and** protected ref; GitHub environment with required reviewers and deployment-branch rules; prod runner group restricted to named repos/workflows; runner machines' own identity has **no** deploy rights; separate Terraform state per tier. Stage 2 missed the last three and built VM images on non-prod runners. | ❌ → **A5** |
| F10 | Quotas | Projects, metrics scopes, Cloud SQL per project | Additional limits now in scope: IAM 1,500 principals/policy (A2); Cloud Logging 30 log views per bucket (increase to 1,000) and 200 sinks per project (increase to 4,000); Cloud SQL instances per project (read replicas count); GKE/Cloud Run admin API write rates during fleet rollouts; project-creation quota. | ⚠ Quota register to be created in Stage 4 → B14 |

---

## 3. Security and isolation

### 3.1 Logical vs infrastructure isolation

"Physical" isolation (dedicated hardware) is **not used anywhere**; everything runs on Google's multi-tenant infrastructure. Sole-tenant nodes would be the option if a contract required it **[Q]**.

| Boundary | Kind | What relies on it |
|---|---|---|
| Tenant GCP project | Infrastructure (IAM, quota, billing, audit boundary) | Buckets, secrets, keys, workload SAs, Cloud Run, MIGs, dedicated DBs |
| Prod VPC vs non-prod VPC | Infrastructure (no route) | Prod/non-prod network separation |
| Per-tenant KMS key | Cryptographic | Prod buckets and secrets |
| Dedicated Cloud SQL / dedicated GKE cluster | Infrastructure | Enhanced / Dedicated tiers |
| Enhanced-tier dedicated nodes | Infrastructure (separate VMs), **placement enforced logically** (tolerations + admission policy) | Enhanced tier on shared clusters |
| GKE namespace + RBAC + NetworkPolicy | Logical | Every Standard-tier GKE workload |
| Shared GKE nodes | Logical (shared kernel) | Standard-tier GKE workloads |
| Pooled Cloud SQL database | Logical (same PostgreSQL server) | Every Standard-tier database |
| Shared subnets / Shared VPC | Logical for tenant-to-tenant (relies on IAM + auth + NetworkPolicy + firewall) | All workloads in a tier |
| Shared ALB URL map / shared Gateway | Logical (configuration) | All customer front doors |
| Central log buckets + log views | Logical | Customer support log access |
| Shared deployer identity per tier | Logical (one identity can change every tenant in the tier) | All deployments |
| Shared / Cohort product deployments | Application code | Products that opt into those models |

### 3.2 How the layers combine (Standard tier, GKE)

A pod in `abc-payroll-prd` can only act as `payroll-prd@t-abc-prd` (Workload Identity, namespace-scoped). That identity has IAM only on ABC resources (project boundary). It reaches PostgreSQL over a network path every tenant shares, so the **database grant is the only control** for pooled data. It is denied pod-to-pod traffic to XYZ by NetworkPolicy, which requires the policy to exist **before** the workload starts. So the strength of Standard-tier isolation is the *weakest* of: namespace provisioning order, Workload Identity scoping, PostgreSQL privileges and the shared Gateway configuration. That is why A3 and A6 are critical.

### 3.3 Potential customer-to-customer access paths

| # | Path | Stage 2 control | Gap | Correction |
|---|---|---|---|---|
| X1 | ABC's DB user connects to `xyz_payroll` on a pooled instance | "CONNECT only on own DB" | `PUBLIC` has `CONNECT`/`TEMP` on all databases by default; catalog visible | **A3:** revoke from `PUBLIC` on every database and `template1`; automated cross-tenant connection test after every onboarding |
| X2 | ABC's HTTPRoute claims `xyz.payroll.example.com` on the shared Gateway | Gateway accepts routes from namespaces labelled `product=payroll` | Any payroll namespace may claim any payroll hostname | **A6:** admission policy – route hostnames must equal hostnames derived from the namespace's `tenant`/`env` labels; validator rejects free-form hostnames |
| X3 | Wrong host rule in a shared ALB URL map | Generated by pipeline | Not stated that the map is generated only from the registry | **A6:** URL maps generated from the registry; config test asserts host → backend project = tenant |
| X4 | Container escape on shared nodes | Autopilot hardening | Inherent to shared kernels | Documented residual risk; Enhanced/Dedicated tiers; GKE Sandbox as an option to validate **[Q21]** |
| X5 | Namespace `abc-payroll-prd` created in another cluster of `plt-gke-prd` inherits ABC's identity | – | Identity sameness not addressed | B12: only platform cells in `plt-gke-*`; cluster creation and namespace creation restricted to the platform pipeline; dedicated-tier clusters live in tenant projects (own pool) |
| X6 | Shared deployer SA (or template injection through a tenant file) writes into another tenant | Single deployer per tier | One identity can change every tenant | Validation rejects any resource reference not derived from the tenant slug (A7 schema); B1: per-tenant prod deployer identities |
| X7 | Pool admin credential (built-in user used by the DB bootstrap job) leaked | Not described | Full access to every tenant DB on the pool | Credential in Secret Manager in the pool project, readable only by the per-tier bootstrap job; `pgaudit` on pools; rotation |
| X8 | Network reachability between tenants on shared subnets | Firewall + NetworkPolicy | Cloud SQL private IPs are reachable by every workload in the tier | Accepted by design: authentication + A3 are the control; Cloud Run has no VPC ingress; MIG firewall allows LB ranges only |
| X9 | Ansible controller can reach every tenant VM in the tier | OS Login + IAP | Controller identity is tier-wide | B15: per-run impersonation of a tenant-scoped ops identity; inventory restricted by labels |
| X10 | Log views / dashboards mis-scoped | Log views per tenant | Logs may contain PII | Generated from registry; PII-in-logs guideline for product teams |
| X11 | Shared / Cohort products | ADR-006 | Isolation is in application code by definition | Product security review is a precondition for using those models |

### 3.4 Potential prod ↔ non-prod paths

| # | Path | Direction | Stage 2 status | Correction |
|---|---|---|---|---|
| P1 | Masking pipeline writes masked dumps to non-prod | prod → non-prod (intended) | Designed, approved per refresh | Keep; document VPC-SC egress rule for this one bucket (K7) |
| P2 | **Images, charts and VM images built where non-prod pipelines run, then pulled by prod** | non-prod → prod | Diagram 05 bakes VM images on the non-prod runner; Artifact Registry writers not separated | **A5:** dedicated build project `shr-build` with its own identity; release repositories writable only by the build pipeline; prod pulls by digest; Binary Authorization in prod (recommended) |
| P3 | **Terraform state for prod and non-prod in one bucket** | non-prod → prod | Single `bootstrap-seed` state bucket | **A5:** one state bucket per tier, separate IAM |
| P4 | Prod runner picked by a non-prod or unrelated workflow | non-prod → prod | Not addressed | **A5:** runner groups restricted to platform repos/workflows; runner VM identity has no deploy rights |
| P5 | Shared tenant-registry repo | both | Prod jobs gated by GitHub environment `prd` | Keep; add deployment-branch rule and CODEOWNERS for `prd` version lines |
| P6 | GitHub org owners / platform admins | both | Not discussed | Residual: treat as privileged identities (MFA, audit-log streaming, minimal count) |
| P7 | Shared observability projects | read-only | OK | No change |

### 3.5 Controls that are recommendations, not guaranteed boundaries

VPC Service Controls (Phase 6) · Binary Authorization (new) · Policy Controller constraints · Privileged Access Manager · CMEK · Cloud NGFW FQDN egress rules (paid tier) · alerting on cross-tenant IAM grants · masking verification step · Enhanced / Dedicated tiers · per-tenant deployers · DR. Each reduces risk but none is in place until implemented and tested; the architecture document now labels them **[R]**.

### 3.6 Identity types reviewed separately

| Identity type | Strength | Weakness found | Action |
|---|---|---|---|
| Humans | Groups, SSO with MFA, no standing prod write, PAM, break-glass | GitHub admins are effectively prod-capable; customer-support log access depends on log-view quotas | P6, B5 |
| Pipelines | Keyless WIF, separate prod/non-prod SAs | Enforcement conditions incomplete; shared state; build in non-prod; tier-wide blast radius | A5, B1 |
| Workloads | One SA per customer-product-env, keyless | Project-level SQL roles hit policy limits; PUBLIC DB privileges; identity sameness | A2, A3, B12 |

---

## 4. End-to-end consistency

| # | Inconsistency | Where | Fix |
|---|---|---|---|
| K1 | GKE traffic drawn through `plt-ingress-prd`, but text says the GKE Gateway creates its own LB in the cluster project | Diagram 02 vs §2A | Diagram 02 corrected |
| K2 | `tier` means both prod/non-prod (naming table) and standard/enhanced/dedicated (registry, tags) | Naming, registry, diagram 01 | Renamed: `env_tier` (prd/nonprd) and `isolation_tier` (standard/enhanced/dedicated) |
| K3 | Registry `placement` lists prod pools only; no Dev/Stage/UAT cluster or pool placement | §3.1 | Registry schema v2 with per-environment placement |
| K4 | Shared/Cohort models (ADR-006) have no project, namespace or registry representation | ADR-006, naming, registry | Product projects `p-<product>-<env_tier>`, namespaces `shr-…`/`coh-…`, registry fields |
| K5 | VM images built on the non-prod runner but used in prod | Diagram 05 vs §5.4 | `shr-build` (A5) |
| K6 | `restricted.googleapis.com` used before VPC-SC exists; "workload tag" rules for Cloud Run | Diagram 11 | `private.googleapis.com` until VPC-SC; network tags for Cloud Run |
| K7 | Masking job writes outside a future prod VPC-SC perimeter | Diagram 09 vs §5.2 | Explicit perimeter egress rule documented |
| K8 | Cloud SQL instance estimates contradict per-product prod pools | §6.1 | Replaced by capacity model |
| K9 | "One cluster per tier" vs 1,000-namespace heuristic | §6.2 | ADR-008 |
| K10 | Pooler options ignore edition requirement | §6.3 | A4 |
| K11 | "IAM user has CONNECT on its own database only" stated as a fact | §4.4, diagram 03 | Now conditional on A3 hardening |
| K12 | Default-deny egress NetworkPolicy omits DNS and the GKE metadata server (needed by Workload Identity) | Diagram 03, §2A | Noted; rule catalogue in Stage 4 |
| K13 | Dedicated-tier **non-prod** treatment undefined (`t-bigco-nonprd` shown without explanation) | Diagram 01 | Default: non-prod uses shared tiers; **[Q18]** |
| K14 | Offboarding says databases are dropped, but pooled backups keep that customer's data until backup retention expires | Diagram 07 | Stated in diagram + **[Q19]** |
| K15 | Naming table lacks names for new/split resources (per-env clusters, pool projects, product projects, state buckets, groups, build project) | §0 | Updated |
| K16 | Diagram 01 draws "service project attachment" to folders; attachment is per project | Diagram 01 | Relabelled |
| K17 | Stage 2 §6.1 mixes estimates with no stated inputs | §6.1 | Links to the model with explicit inputs |

All four environments are now represented consistently in: registry schema (versions + placement per env), resource mapping (16 rows), clusters (one per env), SQL pools (one per env), and the workflows (Dev → Stage → UAT → Prod).

---

## 5. Original assignment completeness

| Assignment item | Status | Kind |
|---|---|---|
| §2 hierarchy, isolation, shared services, networking, compute, storage, monitoring; 3-approach comparison | Addressed | Architecture |
| §3 tenant identity, isolation enforcement, logical vs infrastructure isolation | Addressed (strengthened in this review) | Architecture |
| §4 environment management, promotion, prod access | Addressed at architecture level; pipeline detail deferred (Stage 7) | Architecture + implementation |
| §5 GKE / Cloud Run / MIG designs and diagrams | Addressed; "shared vs dedicated clusters" now explicit via cells + tiers | Architecture |
| §6 versioning: images, Artifact Registry, chart versions, values files, Terraform variables | **High level only** – values layering and Terraform variables deferred (Stages 5–6) | Implementation |
| §7 data: masking, backup, retention | Addressed; **retention periods and erasure from backups undefined [Q11, Q19]** | Architecture + company decision |
| §8 security: vulnerability management, security monitoring, org policies, full access matrix | **High level only** – Stage 3 | Architecture |
| §9 Terraform | Deferred – Stage 5 | Implementation |
| §10 Helm | Deferred – Stage 6 | Implementation |
| §11 self-service: GitOps vs portal evaluation | **Inadequately addressed** – repo-based flow designed, portal trade-off not yet written (Stage 7) | Architecture |
| §12 shared infrastructure: Ansible execution environment, Terraform execution environment, runner isolation | Partially – strengthened by A5; execution-environment detail Stage 7 | Architecture + implementation |
| §13 Terraform failures, CI/CD failures, SLI/SLO definitions | **Missing so far** – Stage 8 | Architecture |
| §14 cost allocation, billing reports, idle resources | **High level only** – Stage 8 | Architecture |
| §15 diagrams | Addressed | Architecture |
| §16 sample configs for ≥2 customers × 2 products | Registry examples only; Helm/Terraform samples Stages 5–6 | Implementation |
| §17 phases | Deferred – Stage 8 | Architecture |

---

## 6. Findings by category

### A. Critical – must be resolved before Stage 3

| ID | Issue | Why it matters | Recommended correction | Applied? |
|---|---|---|---|---|
| **A1** | Capacity model fixed at 3 products/customer; one non-prod cluster; Cloud SQL counts understated | Topology is invalid in common scenarios (e.g. 200 × 5); cost and quota planning would be wrong | Variable-subscription model; **one GKE cluster per environment** with cells (ADR-008); prod SQL pools per product **group**, pool projects sharded (ADR-003 rev. 2) | ✅ |
| **A2** | Project-level IAM grants per workload SA exceed the 1,500-principal allow-policy limit (SQL pools at 200 × 3; also Artifact Registry and Shared VPC grants at scale) | Onboarding would fail once the policy is full; cannot be raised | **Fleet-wide grants to Google groups** maintained by the project factory; per-tenant authorization stays at resource and database level (ADR-009) | ✅ |
| **A3** | PostgreSQL default `PUBLIC` privileges allow cross-tenant `CONNECT`/`TEMP` on pooled instances | The central isolation claim for pooled databases was false by default | Database hardening baseline in the DB bootstrap job (revoke from `PUBLIC` on each database and `template1`; no `CREATE` on `public` schema; IAM users only for apps; no built-in users for apps) + **automated cross-tenant denial test** on every onboarding | ✅ (design) |
| **A4** | Connection pooling assumed without the edition dependency | The pooled-DB capacity (tenants per instance) depends on it | Default: client-side pools with a per-pool **connection budget** enforced by capped replicas/instances; Managed Connection Pooling only on Enterprise Plus pools after validating IAM auth with it; edition is a company decision **[Q16]** | ✅ (design) |
| **A5** | Non-prod → prod paths: images built by non-prod pipelines, shared Terraform state, unrestricted prod runners | Breaks the "prod/non-prod isolated" requirement **[C10]** | `shr-build` build project and identity; release repos writable only by build; prod pulls by digest; Binary Authorization for prod [R]; **state bucket per tier**; runner groups; WIF conditions on repository ID + environment + ref (ADR-010) | ✅ |
| **A6** | Hostname hijack on shared Gateway / URL maps | Direct customer-to-customer traffic interception path | Hostnames derived from registry only; admission policy on HTTPRoutes; URL-map config tests | ✅ (design) |
| **A7** | Registry/naming inconsistencies: no non-prod placement, no home for Shared/Cohort products, overloaded `tier` | The registry is the system of record; Stage 3 IAM and Stage 5 Terraform build on it | Registry schema v2, product projects, label rename | ✅ |

### B. Important – can be resolved later (stage noted)

| ID | Item | Stage |
|---|---|---|
| B1 | Per-tenant deployer identities for prod to reduce pipeline blast radius | 3 (decision), 7 (build) |
| B2 | Confirm Shared VPC service-project quota; if binding, network cells | 4 |
| B3 | PSA allocated-range sizing for hundreds of Cloud SQL instances; PSC alternative | 4 |
| B4 | Fleet-wide IAM via groups: group propagation delay and Cloud Identity API automation | 3, 5 |
| B5 | Per-tenant log views exceed 30/bucket default → quota increase (≤1,000) per cell bucket, or log routing to tenant projects | 3, 8 |
| B6 | Metrics scope sharding at 500 customers | 8 |
| B7 | URL map quota-unit sizing; one map per product per env | 4 |
| B8 | Cloud Run egress subnet sizing (≈2 IPs per instance); non-RFC1918 options | 4 |
| B9 | Fleet rollout parallelism vs GitHub and Google API quotas | 7 |
| B10 | MIG Dedicated cost floor → prioritise Cohort/Shared for MIG products; schedule non-prod to zero | 8 |
| B11 | Policy Controller/Gatekeeper on Autopilot (support + licensing) | 3 |
| B12 | Workload Identity identity-sameness rules enforced by IAM/org policy | 3 |
| B13 | Pool size cap by storage/restore time, not only tenant count | 4, 8 |
| B14 | Quota register (all limits above with owners and alert thresholds) | 4 |
| B15 | Tenant-scoped Ansible operations identity | 6, 7 |
| B16 | Data sharing inside non-prod (e.g. Stage → UAT refresh) not described | 4 |
| B17 | NetworkPolicy egress must allow DNS and metadata server | 4 |

### C. Assumptions and decisions requiring company confirmation

New or changed in this review (full list in the register): **A14** average subscriptions unknown · **A15** runtime mix unknown · **A16** every product needs a relational DB · **Q16** Cloud SQL edition for pools (Enterprise vs Enterprise Plus) · **Q17** do a customer's products call each other · **Q18** dedicated-tier customers' non-prod isolation · **Q19** erasure of an offboarded customer's data from pooled backups · **Q20** actual Shared VPC service-project quota · **Q21** need for sandboxed containers (GKE Sandbox) or sole-tenant nodes for any customer. Existing Q1–Q15 remain open.

### D. Proposed architecture changes

| ID | Change | Justification | Alternatives | Trade-offs |
|---|---|---|---|---|
| D1 | One GKE cluster per environment (`gke-dev/stg/uat/prd-as1-NN`), sharded into cells (ADR-008) | Namespace counts; upgrade canary order Dev → Stage → UAT → Prod; smaller blast radius | One non-prod cluster with earlier sharding; cluster per product | +3 cluster fees and upgrade streams vs. predictable growth and safer upgrades |
| D2 | Fleet-wide IAM grants via Google groups (ADR-009) | IAM policy limit | Shard projects only; per-instance… (not available for Cloud SQL) | Group-membership propagation delay; Cloud Identity automation required |
| D3 | Prod SQL pools per product group, split per product as adoption grows; pool projects sharded (ADR-003 rev. 2) | Avoid ~20 idle prod instances at low adoption; per-project instance limit | Strict per-product pools | Mixed-product pools share engine version/maintenance across those products |
| D4 | Separate build from deploy: `shr-build`, release repos, Binary Authorization; state bucket per tier; runner groups (ADR-010) | Non-prod → prod supply-chain and state paths | Separate Artifact Registry per tier with promotion copy | One more project/pipeline; signing key management |
| D5 | Product projects `p-<product>-<env_tier>` and namespaces `shr-…`/`coh-…` for Shared/Cohort (ADR-006 rev.) | Give those models a home and a boundary | Put them in platform projects | More projects (≤ 2 per Shared/Cohort product) |
| D6 | Registry schema v2 (per-env placement, subscription-level blocks, deployment model aware); label rename | Consistency, variable subscriptions | – | Schema migration of examples only (nothing deployed) |
| D7 | PostgreSQL hardening baseline + cross-tenant denial test (ADR-003 rev. 2) | A3 | Schema-per-tenant (worse) | One more onboarding step |
| D8 | Pooling strategy decision (A4) | Edition dependency | Self-run PgBouncer with IAM | Enterprise Plus cost vs. connection efficiency |
| D9 | Hostname policy for Gateway / URL maps | A6 | Gateway per tenant (cost, LB count) | Admission policy to maintain |

### E. Artifacts updated

See §7. Every change carries a review ID (A1…A7, K1…K17) in [`CHANGELOG.md`](../CHANGELOG.md).

---

## 7. Changes applied in this review

| Artifact | Change | Review IDs |
|---|---|---|
| `documentation/capacity-model.md`, `scripts/capacity_model.py` | New: variable-subscription model | A1 |
| `architecture/stage-2-platform-architecture.src.md` (+ generated `.md`) | Naming (§0), components (§1.3), GKE/SQL text, registry v2 (§3.1), mapping (§4.3), isolation (§4.4), security (§5), scalability (§6) rewritten to the model, ADR table, change log | A1–A7, K1–K17 |
| Diagrams 01–12  | Updated (per-env clusters, build project, state per tier, groups, hostname policy, PGA VIP, VPC-SC note, retention note, labels) | A1, A2, A5, A6, A7, K1–K16 |
| ADR-003, ADR-005, ADR-006 | Revised | A1, A3, A4, A7 |
| ADR-008, ADR-009, ADR-010 | New | A1, A2, A5 |
| `documentation/assumptions-and-open-questions.md` | A13 revised; A14–A16, Q16–Q21 added | C |
| `documentation/requirements-traceability.md` | Updated statuses | §5 |

---

## 8. Final review checklist

**Reviewed**
- [x] Capacity across 1/3/5/10/15/20 products × 200/500 customers, all three runtimes, three deployment models
- [x] GKE namespaces prod vs non-prod; cells vs the 1,000-namespace heuristic (planning assumption)
- [x] Cloud SQL capacity, IAM policy size, projects, metrics scopes, CI/CD concurrency
- [x] Shared VPC, cross-project LB, Autopilot, Workload Identity, NetworkPolicy, workload separation
- [x] Cloud SQL connectivity, IAM DB auth, pooling, backup and per-tenant recovery
- [x] Prod/non-prod CI separation enforceability
- [x] Customer-to-customer and prod ↔ non-prod paths; logical vs infrastructure isolation; human/pipeline/workload identities
- [x] Consistency across diagrams, mapping, naming, registry, catalogue, ADRs, register, workflows, four environments
- [x] Assignment completeness; architecture vs implementation deliverables

**Corrected**
- [x] A1–A7 (design corrections applied to documents, diagrams and ADRs)
- [x] K1–K17 consistency fixes

**Unresolved (tracked, not blocking Stage 3)**
- [ ] Company answers: Q1–Q21 (especially Q2 regulation, Q3 pooled prod DBs, Q16 Cloud SQL edition, Q19 erasure from backups)
- [ ] Validation items needing a test project: Shared VPC quota value (Q20), Managed Connection Pooling with IAM auth, Policy Controller on Autopilot, URL-map quota units, PSA range sizing
- [ ] B1–B17 scheduled in later stages

**Ready for Stage 3?** **Yes, conditionally.** All critical issues have a documented correction that Stage 3 can build on. Stage 3 should start by turning A2 (group-based IAM), A5 (pipeline identities) and B1/B11/B12 into the concrete access-control matrix and policy set. Company answers to Q2, Q3 and Q16 may change tier and pool choices but not the access model.


---

## Addendum – Stage 2 final reconciliation (MySQL, groups, capacity)

New IDs were added only where the earlier IDs did not cover the issue.

| ID | Category | Finding | Correction | Supersedes |
|---|---|---|---|---|
| **M1** | Critical | Cloud SQL for MySQL derives the IAM database username from the SA's local part (≤ 32 chars); `payroll-prd@t-abc-prd` and `payroll-prd@t-xyz-prd` would collide on a shared pool | Workload SA IDs `<cust>-<product>-<env>[-mig]` | – |
| **M2** | Critical | MySQL connections are not bound to a database; isolation is privilege-only; wildcard (`_`, `%`) database grants; `PROCESS`, `mandatory_roles` risks | Per-database roles, escaped grants, no global privileges, hardening baseline, ISO-01…10 gate | A3, X1 |
| **M3** | Important | `DEFINER` objects can run with another account's privileges | Definer = tenant migration account only; no `SET_ANY_DEFINER`/`SET_USER_ID` for tenant accounts | – |
| **M4** | Important | 50,000-table default limit per instance | Pool sizing input (capacity model) | – |
| **M5** | Important | Managed Connection Pooling for MySQL needs Enterprise Plus and restarts the instance; IAM support undocumented | App-side pooling default; T-M5 | A4 (PostgreSQL part), F7 |
| **M6** | Important | Built-in users get `cloudsqlsuperuser` automatically | Apps use IAM SA accounts only; bootstrap identity separate; root sealed | F6 |
| **M7** | Important | Non-transactional DDL | Separate migration identity, expand/contract, pre-migration backup | – |
| **M8** | Important | Single-tenant restore on MySQL | Clone + per-database export/import; T-M8 | – |
| **G1** | Design | Hybrid groups model with three identity categories | ADR-009 rev. 2 | – |
| **G2** | Validation | Group-inherited `cloudsql.instanceUser` for individual IAM users not explicitly documented | T-G2 + fallback (shard pool projects by SA count) | – |
| **G3** | Design | IAM group DB auth gives all members the same DB privileges | Humans only | – |
| **G4** | Important | Per-customer log views in one project would exceed 250 groups per policy | Route customer GKE logs to tenant projects | B5 |
| **G5** | Important | Group management is security-critical | Automation as group manager, drift detection, quarterly review | – |
| **C1** | Critical (consistency) | Capacity model ignored product-group pooling | Model rev. 2 with groups, split rule, four capacity constraints | part of A1 |
| **C2** | Consistency | "Projects = 2 × customers" overstated | Tenant / product / infrastructure categories | – |
| **C3** | Consistency | ~40% Shared/Cohort saving presented as a result | Marked illustrative; four counts separated; extra app responsibilities | – |

### Final corrections (2026-11-22)

| ID | Finding | Correction |
|---|---|---|
| **K18** | Slug limits allowed a 31-character migration SA ID; Google allows 6–30 | Customer ≤ 10, product ≤ 11, no hyphens in slugs; registry schema v2.1; validator + boundary tests |
| **K19** | "Groups never carry tenant data access" contradicted DBA groups with database privileges | Workload groups: infrastructure permissions only; human role groups: centrally approved role-based privileges; no group grants cross-customer database access |
| **K20** | Project-IAM-policy groups and Cloud SQL IAM group authentication were not clearly separated | Mechanism 1 (workloads, connect only, T-G2 mandatory) vs mechanism 2 (human DBAs, ≤ 3 of 200 groups per instance); workload SAs never in mechanism-2 groups |

### Stage 3 clarifications

| ID | Finding | Correction |
|---|---|---|
| **K21** | Stage 2 said DBA-admin group membership comes "only through PAM"; PAM grants temporary IAM role bindings to the requester and cannot grant group membership | Time-bound group membership with expiry after approval; PAM remains for IAM-role elevation; test T-G6 |
| **K22** | "No group spans prod and non-prod" contradicted one customer-support group bound in both tenant projects | `grp-hum-cust-<tenant>-support-prd` / `-nonprd`, derived from the registry's support-group prefix |

**Readiness after reconciliation:** all critical items (M1, M2, C1) have documented corrections. Open items are company decisions (Q-list) and validation tests (T-list) in [`assumptions-and-open-questions.md`](assumptions-and-open-questions.md).
