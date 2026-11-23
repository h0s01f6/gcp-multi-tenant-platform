# Assumptions, recommendations and open questions

> Living register. Nothing here is a confirmed company requirement unless marked **Confirmed**.
> Last updated: Stage 3 completion (2026-11-23, D11). Items added or changed by the review are marked *(review)*; by the reconciliation *(recon)*; Stage 3 items carry their deliverable (D1–D10).
> Consistency is tested: every validation, risk and assumption ID referenced anywhere in the repository must exist here exactly once (`tests/test_registers.py`).

## Confirmed requirements (from the assignment)

| ID | Requirement |
|---|---|
| C1 | 200+ customers, 15–20 products, growth to 500+ |
| C2 | Four environments per customer: Dev, Stage, UAT, Prod |
| C3 | A customer can use multiple products |
| C4 | Products run on GKE, Cloud Run or Compute Engine MIGs |
| C5 | Different customers may run different versions of the same product |
| C6 | Customer- and product-specific configuration and customisation |
| C7 | Customer data isolated; controlled sharing only between a customer's own environments |
| C8 | Shared infrastructure for GitHub/Bitbucket repositories and Ansible runners |
| C9 | Easy to operate, automate and extend; self-service onboarding |
| C10 | Production isolated from non-production; automation uses dedicated identities |
| C11 | Terraform (GCS remote state, modules, approvals) and Helm; no hard-coded credentials, secrets or project IDs |
| C12 | Prefer managed GCP services and native monitoring |

## Assumptions (need company confirmation)

| ID | Assumption | Impact if wrong |
|---|---|---|
| A1 | Products are deployed one instance per customer by default (Dedicated model); some may be Shared/Cohort (ADR-006) | Deployment count, cost, DB pattern |
| A2 | Customer end users reach products only through the application, not the GCP console; "customer-specific users" are internal staff assigned to a customer | Customer-facing IAM/console access would need a different design |
| A3 | A corporate IdP exists and can federate with Google Cloud | Human authentication design |
| A4 | Primary region asia-south1, DR region asia-south2; no per-customer data residency by default | Region pair, DR design, storage replication options |
| A5 *(recon)* | ~~Cloud SQL for PostgreSQL~~ → **Cloud SQL for MySQL 8.4** is the relational database (stakeholder decision, ADR-011). Remaining assumption: every product supports MySQL 8.4 | Products needing PostgreSQL would need an exception pool |
| A6 | GitHub + GitHub Actions (Bitbucket equivalents noted) | CI/CD implementation details |
| A7 | UAT uses masked data and stays in the non-prod tier | UAT placement, data controls |
| A8 | Prod targets: 99.9% availability, RPO ≤ 15 min, RTO ≤ 4 h for a regional disaster (placeholders) | DR cost and topology |
| A9 | Application-level authentication of customer end users (login, customer SSO) is owned by each product, not the platform | Platform might need an identity service |
| A10 | No hybrid connectivity to on-premises or other clouds is required | Would add Interconnect/VPN, IP planning constraints |
| A11 | `example.com` is a placeholder for the real domain(s) | DNS and certificate design |
| A12 | GKE/Cloud Run products are containerised; MIG products can be baked into VM images | Build pipeline design |
| A13 *(review)* | Sizing heuristics are **planning assumptions, not GCP limits**, to be validated by load testing: ~1,000 namespaces per GKE cell, ~30–50 tenant DBs per prod pool, ~100 per non-prod pool, ~100 instances per pool project, connection budget ≤ ~70% of `max_connections` | Number of cells, pools and pool projects |
| A14 *(review)* | The average number of products per customer is unknown and will vary widely (1 to most of the catalogue); planning uses scenarios 1/3/5/10/15/20 | All capacity numbers (see capacity model) |
| A15 *(review)* | The split of products across GKE / Cloud Run / MIG is unknown; planning uses an illustrative 50/35/15 mix plus a 100%-GKE worst case | Cluster cells, MIG cost |
| A16 *(review)* | Every subscription needs its own relational database (capacity model also shows a 60% case) | Cloud SQL pool counts: e.g. 500 × 10 → 442 instances at 100%, 259 at 60% |
| A17 *(recon)* | Products in a product group, and all products in a non-prod pool set, use the same MySQL major version (8.4) | Otherwise more pools (one set per version) |
| A18 *(recon)* | Illustrative database sizing: prod pool 8 vCPU / 32 GB, `max_connections` 4,000; non-prod 4 vCPU / 16 GB, 2,000; 20 GB (prod) / 5 GB (non-prod) per tenant DB growing 30%/yr; 300 tables per tenant DB | Tenants per pool and therefore instance counts (capacity model T3/T5) |

## Recommendations made in this design (see ADRs)

R1 hybrid project model (ADR-001) · R17 hybrid groups model – groups for identical non-data permissions, individual workload SAs (ADR-009 rev. 2) *(recon)* · R18 MySQL isolation baseline + mandatory ISO-01…10 gate (ADR-003 rev. 3) *(recon)* · R19 Enterprise Plus for prod pools *(recon)* · R13 one GKE cluster per environment, cells (ADR-008) *(review)* · R14 fleet-wide IAM via groups (ADR-009) *(review)* · R15 build/deploy separation, signed artifacts, state per tier (ADR-010) *(review)* · R16 ~~PostgreSQL hardening baseline~~ superseded by R18 *(review, recon)* · · R2 environment-first folders (ADR-002) · R3 pooled Cloud SQL, database per customer-product (ADR-003) · R4 dedicated tier (ADR-004) · R5 GKE Autopilot (ADR-005) · R6 deployment models (ADR-006) · R7 two projects per customer (ADR-007) · R8 tenant registry in Git as the self-service interface · R9 separate prod/non-prod CI runners and deployer identities · R10 Prod → non-prod data only through a masking pipeline · R11 VPC Service Controls in Phase 6 (dry-run first) · R12 Dev environments not always-on (scale-to-zero / scheduled scale-down).

## Open questions (company must answer)

| ID | Question | Who decides | Default used until answered |
|---|---|---|---|
| Q1 | Which products are multi-tenant or Cohort-capable? | Product teams | All Dedicated |
| Q2 | Any regulatory or data-residency requirements? Which customers? | Legal / compliance | None; Dedicated tier and location policies ready |
| Q3 | Are pooled prod databases acceptable contractually? Per-customer RTO/RPO? | Business + legal + engineering | Pooled (database per customer-product) |
| Q4 | Must every customer's Dev be always-on? | Engineering teams | No: scale-to-zero and scheduled scale-down |
| Q5 | Does any customer require real prod data in UAT? | Data owners, contracts | No: masked data only |
| Q6 | Are the required security/monitoring agents supported on GKE Autopilot? | Security + platform | Autopilot, Standard fallback |
| Q7 *(recon)* | ~~Database engine~~ – **decided: Cloud SQL for MySQL 8.4**. Remaining: confirm every product is certified on MySQL 8.4 | Product teams | MySQL 8.4 |
| Q8 | Identity provider, Git platform, regions | IT / platform | Generic IdP, GitHub, asia-south1/2 |
| Q9 | Is hybrid connectivity needed? | Network / IT | No |
| Q10 | Is regional DR required for all customers, or only some tiers? | Business | Pilot-light DR for prod |
| Q11 | Backup retention after a customer offboards | Legal | Placeholder: per contract |
| Q12 | Are any MIG products stateful (local disks)? | Product teams | Stateless |
| Q13 | Key placement: tenant project vs central key project per tier | Security team | Tenant project |
| Q14 | Self-hosted runners (ARC) vs GitHub-hosted runners for deploy jobs | Platform + security | Self-hosted, ephemeral |
| Q15 | Should UAT pools be HA? | Engineering + finance | HA for UAT, zonal for Dev/Stage |
| Q16 *(review, recon)* | Cloud SQL edition for pools. Recommendation: **Enterprise Plus for prod pools** (one maintenance event affects every tenant; Managed Connection Pooling needs it), Enterprise for non-prod | Engineering + finance | Enterprise Plus prod, Enterprise non-prod |
| Q17 *(review)* | Do a customer's products call each other (cross-product traffic within one customer)? | Product teams | No; affinity placement keeps it possible |
| Q18 *(review)* | Do Enhanced/Dedicated customers need isolated non-prod too? | Business + contracts | No: shared non-prod tiers with masked data |
| Q19 *(review)* | Is retention of an offboarded customer's data inside pooled backups (until expiry) acceptable for erasure obligations? | Legal / compliance | Placeholder: retention-limited deletion, documented to the customer |
| Q20 *(review)* | Actual Shared VPC service-projects-per-host quota for the org | Platform (console check) | Assume quota increase is possible; network cells if not |
| Q21 *(review)* | Does any customer require sandboxed containers (GKE Sandbox) or sole-tenant nodes? | Security + contracts | No |
| Q22 *(recon)* | Real per-product database sizes, growth and table counts | Product teams | Illustrative A18 values |
| Q23 *(recon)* | Google Workspace or Cloud Identity (Free/Premium) for groups; who owns group administration; can automation identities be group managers | IT / security | Cloud Identity groups managed by automation as group managers |
| Q24 *(recon)* | Does any product need PostgreSQL-only features (e.g. row-level security, specific extensions)? | Product teams | No |
| Q25 *(D10)* | Paging integration for security alerts (PagerDuty, phone, other) and the security on-call rota | Security team | E-mail channel only until decided |

## Technical validation tests (need a GCP test project – nothing below has been tested)

| ID | Test | Source |
|---|---|---|
| T-M1 | IAM SA → MySQL username mapping; behaviour when two SAs share a local part | database architecture §3.2 |
| T-M2 | Escaped database names in grants; wildcard canary (ISO-03) on MySQL 8.4 | database architecture §2 |
| T-M3 | `MAX_USER_CONNECTIONS` on IAM SA accounts | database architecture §8 |
| T-M4 | `ACCOUNT LOCK` on IAM accounts takes effect immediately | database architecture §11 |
| T-M5 | Managed Connection Pooling (MySQL, Enterprise Plus) with automatic IAM database authentication | database architecture §8 |
| T-M6 | Cloud Run → Cloud SQL with automatic IAM authentication via the chosen connector | database architecture §3.3 |
| T-M7 | Performance with ~40 tenant DBs × ~300 tables per instance | capacity model |
| T-M8 | Single-tenant restore time (clone + per-database export/import) | database architecture §10 |
| T-G1 | Group-membership propagation for IAM and for Cloud SQL group authentication | identity model §10 |
| T-G2 (**mandatory**) | Group-inherited `cloudsql.instanceUser` (project IAM policy) for individually created IAM SA database users; removal blocks new logins | identity model §4a/§10, ADR-009 rev. 2 |
| T-G3 | IAM group authentication for human DBA groups on MySQL 8.4 (≤ 3 groups per instance vs documented limit of 200) | identity model §4a/§10 |
| T-G6 | DBA-admin JIT via Google Groups membership expiry: expiry removes access; combined with ~15-minute group-auth propagation, the effective start and end times of access (K21) | access matrix, ADR-009 |
| T-K18 | Naming boundary tests (longest valid / invalid IDs) – **passes locally** (`scripts/validate_names.py`, 13/13); real SA creation at 30 characters still to confirm in a test project | registry/naming-rules.md |
| T-G4 | SAs/service agents as group members; automation as manager of specific groups only | identity model §10 |
| T-G5 | Policy behaviour near 250-group limit; per-tenant log sinks to tenant projects | identity model §6 |
| T-N1 | Shared VPC service-projects-per-host quota (Q20) | review B2 |
| T-N2 | Private services access range sizing for the instance counts | review B3 |
| T-K1 | Policy Controller / Gatekeeper on Autopilot (support, licensing) | review B11 |
| T-L1 | URL-map quota units for one map per product per environment | review B7 |
| T-M9 | Isolation harness on Cloud SQL MySQL 8.4: error code per probe, `SHOW DATABASES` visible system schemas, `SHOW GRANTS` output format for IAM users and roles (ISO-02/09 parsers) | `tools/db/README.md` (D4) |
| T-M10 | `isotest-<tier>` impersonates a database-user SA and logs in with automatic IAM database authentication through the connector; token-creator grant limited to that SA set | D4, access matrix `sa-set:db-users-<tier>` |
| T-O1 | List available constraints in the real organisation; confirm managed vs legacy names (`iam.managed.disableServiceAccountKeyCreation`, `essentialcontacts.managed.*`, `compute.managed.*`) and value formats; apply the whole set in dry-run in a test organisation | `security/org-policies.yaml` (D5) |
| T-O2 | Org baseline does not block platform bootstrap (project factory, Shared VPC attachment, Cloud Run / GKE / Cloud SQL creation) | D5 |
| T-O3 | `compute.restrictVpcPeering` with `under:organizations/…` still allows private services access peering for Cloud SQL | D5 |
| T-O4 | `gcp.resourceLocations` value groups cover every service used; global resources unaffected | D5 |
| T-O5 | `compute.restrictSharedVpcSubnetworks` with `under:projects/net-host-<tier>` enforces the tier boundary | D5, Stage 4 |
| T-O6 | Cloud Run `run.allowedVPCEgress = all-traffic` in prod with Direct VPC egress + Cloud NAT | D5, Stage 4 |
| T-K19 | `opa test policies/k8s/src` and `gator verify`; `input.review.namespaceObject` available on the Policy Controller version used | `policies/k8s/` (D8) |
| T-K20 | NetworkPolicy egress needed for Workload Identity on Autopilot (Dataplane V2): GKE docs name `169.254.169.252/32:988` and, for Dataplane V2, `169.254.169.254/32:80` – baseline allows both until confirmed | `security/k8s-baseline.yaml` (D8) |
| T-K21 | Google Groups for RBAC (`gke-security-groups@<domain>`) on the clusters; group subjects in RoleBindings resolve | D8 |
| T-K22 | Pod Security `restricted` accepted by every product image (non-root, no privilege escalation, seccomp RuntimeDefault, dropped capabilities) | D8, Stage 6 charts |
| T-W1 | WIF provider: CEL mapping of the composite `attribute.gate` (`has()`, ternaries, `startsWith`), `:` inside a principalSet attribute value, attribute length limits | `security/cicd-identities.yaml` (D6) |
| T-W2 | GitHub OIDC claims used (`repository_owner_id`, `repository_id`, `environment`, `ref`, `job_workflow_ref`) present for reusable workflows and environment jobs; fork PRs get no token | D6 |
| T-W3 | End to end: a PR-branch job obtains only `tf-plan-<tier>`; a `prd` job outside `platform-workflows` is rejected by the provider condition | D6 |
| T-W4 | Read set needed by `terraform plan` for `tf-plan-*` (refresh of every resource type) and `-lock=false` plans | D6 |
| T-W5 | Bitbucket provider (if A6 changes): claim names and environment handling | D6 |
| T-P1 | PAM entitlements on org and folder resources with the listed roles; requester cannot approve own grant; IAM condition supported in entitlement role bindings | `security/privileged-access.yaml` (D7) |
| T-P2 | Cloud Identity membership with expiry for `grp-hum-dba-prd-admin`; a group manager role scoped to one group | D7, T-G6 |
| T-P3 | Break-glass drill: super-admin login with hardware key, membership with expiry, all `required_alerts` fire | D7, D10 |
| T-S1 | CMEK keys exist and service agents are granted before prod buckets, secrets and pools are created; then lift the D5 CMEK constraints out of dry-run | `security/data-protection.yaml` (D9) |
| T-S2 | Binary Authorization on Cloud Run with the project default policy; `run.allowedBinaryAuthorizationPolicies = default` | D9, D5 |
| T-S3 | `compute.trustedImageProjects = shr-build` on tenant/platform folders does not block GKE Autopilot or dedicated-tier GKE nodes | D9, D5 |
| T-S4 | GKE Autopilot clusters with Binary Authorization `PROJECT_SINGLETON_POLICY_ENFORCE`; attestor verifier role for each project's Binary Authorization service agent | D9, Stage 5 |
| T-S5 | Cross-project CMEK: Cloud SQL service agent of `plt-sql-prd-NN` / `p-*-prd` using keys in `shr-security` | D9 |
| T-S6 | Attestation flow from `shr-build` (HSM key signing, occurrence in `shr-build`) verified by a prod deploy; break-glass annotation logged | D9 |
| T-A1 | Google Workspace / Cloud Identity audit sharing to Cloud Logging: group membership events (`admin.googleapis.com`) and admin logins (`login.googleapis.com`) reach the org sink; field paths used in AL-BG-*/AL-DBA-MEMBERSHIP filters | `security/audit-monitoring.yaml` (D10) |
| T-A2 | Log-based alert policies in `shr-security` evaluate entries routed into its bucket by the org sink; notification rate limit and auto-close | D10 |
| T-A3 | Every alert filter fires on a staged event (break-glass drill with T-P3, PAM grant, blocked SA-key attempt, Binary Authorization break-glass on GKE and Cloud Run, KMS key disable, out-of-pipeline IAM change) and not on normal pipeline runs | D10 |
| T-A4 | Nightly exports for drift checks DR01/DR02 (Cloud Asset Inventory IAM policies, Cloud Identity memberships) and their normalisation into `tools/monitoring/drift.py` | D10, Stage 7 |
| T-A5 | Data Access log volume and cost (prod Cloud Storage, Cloud SQL, Secret Manager, KMS); locked-bucket retention behaviour | D10 |
| T-N3 | Build the N1 IP plan in a test organisation: per-cell subnets with named secondary ranges, PSA /16 allocation; Autopilot cell on the named ranges; record the per-node Pod block Autopilot actually chooses (R-N1-1) | `network/ip-plan.yaml` (Stage 4 N1) |
| T-N4 | Shared VPC permissions with Network User only on subnets via `grp-wl-netusers-<tier>`: Cloud Run Direct VPC egress, GKE Autopilot in a service project (host service agent user, firewall rules it needs), MIG instance templates; whether `tf-<tier>` / `deploy-<tier>` also need Network User | `network/vpc.yaml` (N2) |
| T-N5 | Cloud Run Direct VPC egress at scale: IPs per instance, /28 reservation blocks, Cloud Run quota on instances using Direct VPC, start-up delay with Cloud NAT and `all-traffic` egress (R-N2-2) | N2 |
| T-N6 | Cloud SQL private IP through PSA from GKE Pods, Cloud Run and MIG VMs of the same tier; `connector_enforcement = REQUIRED` with IAM database authentication; no path from the other tier | N2 |
| T-N7 | GKE control plane reachable by the deploy runners through the DNS-based endpoint with the IP endpoint's external access disabled | N2 |
| T-N8 | Hierarchical policies on Shared VPC: org and tier-folder rules apply by the VM's project ancestry; `goto_next` for 10.0.0.0/8, IAP and LB ranges lets GKE-managed VPC rules and the network policy decide; GKE control-plane-to-node traffic is not blocked | `network/firewall.yaml` (N3) |
| T-N9 | Network firewall policy egress rules with FQDN objects (Cloud NGFW Standard) sourced by subnet / Pod range and by secure tag; Cloud Run traffic matched by its subnet; rule count per policy | N3 |
| T-N10 | Public zones per product per tier with DNSSEC; Certificate Manager wildcard certificates with DNS authorisation; private zones `googleapis.com` and `pkg.dev` to the Private Google Access VIP (Artifact Registry pulls) ; records per zone | `network/edge.yaml` (N4) |
| T-N11 | Global external ALB in `plt-ingress-<tier>` with cross-project backend services in tenant / product projects (serverless NEGs, instance groups); GKE Gateway `allowedRoutes` by namespace labels; Cloud Armor WAF + rate limit; UAT allow-lists | N4 |
| T-N12 | Cloud NAT manual static IPs and dynamic port allocation for GKE (node + Pod ranges), Cloud Run and MIG subnets at scale; static IP quota per region | N4 |
| T-TF1 | `terraform init` + `validate` + `fmt` of every module and stack; pin exact provider versions; confirm the arguments used exist in that version (GKE `control_plane_endpoints_config`, Certificate Manager `PER_PROJECT_RECORD`, PAM entitlement, org policy `dry_run_spec`, network firewall policy egress rules with source ranges and FQDNs, Cloud Run v2 `vpc_access.network_interfaces.tags`) | `terraform/` (Stage 5) |
| T-TF2 | `terraform plan` of each stack from the generated tfvars in a test organisation; a second plan after apply shows no changes | Stage 5 |
| T-TF3 | End-to-end onboarding sequence for a new customer: tenant -> memberships -> db-bootstrap + isolation gate -> edge -> cluster-config -> Helm release; offboarding in reverse | Stage 5/6 |
| T-TF4 | URL maps in `plt-ingress-<tier>` referencing backend services in customer projects (`compute.loadBalancerServiceUser`), with the Cloud Armor policy of the ingress project attached; fallback: one copy of the policy per backend project | `modules/workloads`, `modules/edge` |
| T-TF5 | Kubernetes provider through the GKE DNS endpoint with a Google access token; `kubernetes_manifest` ordering for ConstraintTemplates -> Constraints (CRDs appear only after the templates are processed – R-TF-1) | `stacks/cluster-config` |
| T-TF6 | State: one gcs prefix per stack instance, locking, plan identities read with `-lock=false`, per-tier bucket IAM | `terraform/stacks.yaml` |
| T-H1 | Real Helm: `helm dependency build`, `helm lint`, `helm template` and `helm install --dry-run=server` of the payroll chart with the generated values; values.schema.json enforced by Helm | `helm/` (Stage 6) |
| T-H2 | Cloud SQL Auth Proxy as a native sidecar (init container with `restartPolicy: Always`) on the GKE version used: start-up order, Job completion, automatic IAM authentication with Workload Identity; proxy image mirrored into the release repository | Stage 6 |
| T-H3 | HTTPRoute attaches to the platform Gateway across namespaces by label selector; HealthCheckPolicy; Gateway certificate-map annotation | Stage 6, N4 |
| T-H4 | Policy Controller (D8 constraints) and Pod Security `restricted` admit every rendered manifest; Binary Authorization admits the signed image | Stage 6, D8, D9 |
| T-AN1 | `ansible-lint`, Packer image bake in `shr-build` with `playbooks/bake-image.yml`, boot-time config loader reading the instance metadata set by Terraform, day-2 `configure.yml` over IAP + OS Login with the `ansible-<tier>` identity | `ansible/` (Stage 6) |
| T-CI1 | `actionlint` on all workflows; pin every third-party action to a commit SHA (now release tags, R-S7-3); hash-pinned `requirements.txt` | `cicd/`, Stage 7 |
| T-CI2 | GitHub App `platform-reader` (contents: read on platform-infra + platform-tenants) used by the workspace action; no other repository readable | Stage 7 |
| T-CI3 | First real pipeline runs in a test GitHub org + GCP test org: WIF claims of jobs in nested reusable workflows (`job_workflow_ref`, `environment`), environment reviewers, per-state concurrency, generated job graph, `applied` marker tag | Stage 7, D6 |
| T-CI4 | Release mechanics: helm OCI pull + `--atomic` rollback, Cloud Run tag/canary + traffic revert, `instance-templates create --source-instance-template --image`, MIG rolling update + revert, smoke test through the LB | Stage 7 |
| T-CI5 | Build gates: Artifact Analysis status/vulnerability fields, `sign-and-create` with the HSM key, Binary Authorization admission, immutable release tags, chart publication, Packer bake in shr-build | Stage 7, D9 |
| T-CI6 | Drift export: `asset search-all-iam-policies` at org scope by `tf-plan-org`; Cloud Identity Groups Reader admin role assigned in the Admin console; DR01/DR02 on real exports | Stage 7, D10 (T-A4) |
| T-CO1 | Replace indicative list prices (us-central1 × 1.12) with asia-south1 prices and negotiated discounts (Pricing Calculator / Billing Catalog API) | `cost/cost-model.yaml` |
| T-CO2 | Measure real sizing and usage (pod requests, log volumes, requests per customer); set up billing export to BigQuery (console only) and the snapshot cleanup policy; per-customer cost queries | Stage 8 |
| T-SL1 | Custom services and request-based SLOs on LB metrics; Gateway-generated backend names match the GKE regex; 500 SLOs per service | `slo/`, observability stack |
| T-SL2 | Log-based SLI metrics for Shared/Cohort products: label extractors, latency value extraction, where LB logs land with cross-project backend services | Stage 8 |
| T-SL3 | Platform alert metrics / log filters / PromQL (burn rate, quota) accepted by Cloud Monitoring and firing on injected faults | Stage 8 |
| T-SL4 | Uptime checks created in tenant projects: per-project limit and free executions, SSL-expiry metric, single alert policy across the scope | Stage 8 |
| T-SL5 | GitHub workflow-failure notifications routed to the platform channel (pipeline signal outside Cloud Monitoring) | Stage 8 |
| T-SL6 | Metrics-scope linking with `monitoring.admin` on both sides; scope performance at the shard size | Stage 8 |
| T-DR1 | Zone failure drill in uat: Cloud SQL HA failover time, GKE/Cloud Run/MIG behaviour (D-2) | `slo/dr.yaml` |
| T-DR2 | Timed PITR clone of a full-size pool to confirm 600 GB/h (A-S8-4) and the 4 h corruption RTO (R-1) | Stage 8 |
| T-DR3 | Backup location vs D5 `gcp.resourceLocations`; custom backup location in asia-south2 once DR is active | Stage 8 |
| T-DR4 | Cross-region replica with CMEK in asia-south2, promotion, DR cells, DNS switch; R-3 timing (after Q10) | Stage 8 |
| T-DR5 | Pre-release on-demand backup as `tf-prd`; restore of a retained backup after instance deletion (R-2) | Stage 7–8 |

## Risk and assumption register (Stage 3 D1–D10, Stage 4 N1–N5, Stages 5–8)

Risks (R-) are accepted design risks with their treatment; assumptions (A-) are values or behaviours to confirm. Open questions they depend on are in the Q table above.

| ID | Item | Treatment |
|---|---|---|
| R-D4-1 | `isotest-<tier>` can mint tokens for every database-user SA of its tier, so it can reach every tenant database in that tier | Resource-level grants on the DB-user SAs only (not folder/project); used only by the gate job (WIF from the protected pipeline, D6); probes are non-destructive and never read rows; alert on any token minted outside the gate job (D10) |
| A-D4-1 | Connection budgets (`MAX_USER_CONNECTIONS`) are representative constants | Replace with per-product values from the capacity model; T-M3 |
| A-D5-1 | Region values (`asia-south1` + `asia-south2` for DR) and CMEK scope are placeholders pending Q10 and D9 | Policies stay in dry-run until confirmed |
| R-D6-1 | `tf-plan-<tier>` is reachable from any branch of `platform-infra` / `platform-tenants` and can read prd metadata, IAM policies and Terraform state | Read-only roles, no secret values (secret metadata only; Terraform never stores values – D9); PR authors already need write access to the repository |
| R-D6-2 | `tf-org` is the most privileged automation identity (security admin, org policy, PAM admin at org) | Environment `org` with two platform-admin reviewers, `main` only, central workflow; all use alerted (D10) |
| R-D6-3 | GitHub organisation owners can change environments and protections | Treated as privileged identities (ADR-010); config drift check in Stage 7 |
| R-D6-4 | B1 decision: one tier-wide prod deployer (`deploy-prd`) instead of per-tenant prod deployers, so a pipeline defect can write into any customer's prod namespace or project | Deploy inputs generated only from the registry (no free-form tenant fields), D8 policies and Binary Authorization limit what can be deployed, prd environment with 2 reviewers; per-tenant deployers revisited with the Stage 7 workflows |
| R-D7-1 | Security-audit members can add themselves to `grp-hum-dba-prd-admin` | Expiry mandatory; AL-DBA-MEMBERSHIP alert; quarterly review |
| R-D7-2 | Break-glass accounts are Cloud Identity super admins (unrestricted) | Sealed, hardware keys, two-person rule, login alert, rotation after every use, quarterly drill |
| A-D8-1 | Network ranges in `k8s-baseline.yaml` (Cloud SQL PSA ranges) are representative until Stage 4 | Regenerate the baseline when Stage 4 fixes the ranges |
| A-D8-2 | Quotas and LimitRange values are representative | Per-product overrides from the capacity model (later stage) |
| A-D8-3 | Helm charts (Stage 6) will not create ServiceAccounts, NetworkPolicies, RBAC or quota objects; images by digest; serving port named `http`; explicit HTTPRoute hostnames | Chart lint in Stage 6/7 |
| R-D9-1 | Tenant keys are administered by `tf-<tier>` (`cloudkms.admin`), so key admins = infrastructure admins | Q13 alternative (central key project per tier) remains open |
| A-D9-1 | Single region (`asia-south1`) for secrets and keys | Extend replication / key locations if DR is required (Q10) |
| A-D9-2 | One attestor (build + scan gates) is enough; no separate QA/UAT attestor | Revisit if a release-approval attestation is required |
| R-D10-1 | AL-BG-USE cannot tell a PAM-activated change from a break-glass change in the log filter | Runbook correlates with AL-PAM-GRANT and AL-BG-MEMBERSHIP; every unmatched human org/folder write is an incident |
| R-D10-2 | AL-ISOTEST-TOKEN is informational; tokens minted outside a gate run are found by the daily correlation, not instantly | Bounded by the resource-level grants (D4); escalate to paging if the correlation is automated (Stage 7) |
| R-D10-3 | Alerts depend on Workspace audit sharing being enabled (group membership, logins) | Enable at org setup; T-A1; AL-AUDIT-CONFIG-CHANGE watches the Cloud side only |
| A-D10-1 | Audit log retention 400 days in the locked bucket is a placeholder | Set from legal retention (Q11); locked retention can only be increased |
| A-D10-2 | Data Access logs for Cloud Storage only in prod folders (volume and cost) | Extend to non-prod only if masked-data handling requires it; T-A5 |
| A-N1-1 | Pods and Services per namespace (prod 3/3, non-prod 2/2) used to size cell ranges | Confirm with product teams (Q22); the checker re-sizes slots if they change |
| A-N1-2 | Cloud Run peak instances per tier (prod 20,000, non-prod 8,000) | Replace with product data; Direct VPC egress subnet is a /16 per tier |
| A-N1-3 | MIG peak VMs per tier (prod 4,500, non-prod 7,000) from the capacity-model floor with autoscaling headroom | Confirm with product teams (B10) |
| R-N1-1 | Autopilot chooses the maximum Pods per node (8–256), so a cell's Pod range may hold fewer nodes than planned at 32 | Each cell slot keeps an equal-size reserve range that can be added as an additional Pod range; T-N3 records the real block size |
| R-N2-1 | `shr-cicd-<tier>` projects sit in `fldr-shared`, where the D5 tier subnet constraint is not set | Generated attachments put each in its own tier only (NW02/NW03); add a project-level subnet constraint in Stage 5 |
| R-N2-2 | Cloud Run with Direct VPC egress and Cloud NAT can see slow connection set-up at instance start | Accepted for the egress-control benefit (D5 `all-traffic` in prod); measure in T-N5 |
| A-N3-1 | All workloads serve on port 8080 (chart port name `http`) | One firewall rule per runtime; Stage 6 charts use it |
| A-N4-1 | Egress destinations in `network/egress.yaml` are illustrative | Product teams supply the real FQDNs and ports before production |
| A-N4-2 | Cloud Armor rate limit 600 requests / minute per client IP | Tune per product from load tests |
| A-N4-3 | UAT customer IP allow-lists are supplied during onboarding | Added to the tenant file in a later schema revision; until then UAT denies by default |
| R-N3-1 | K26: Cloud Run egress can only be matched by subnet, so every Cloud Run product in a tier shares the union of their FQDN allow-lists | Accepted (lists are small and reviewed); per-product granularity would need separate subnets – revisit if a product needs a sensitive destination |
| R-TF-1 | Constraints are custom resources that exist only after their ConstraintTemplates are processed, so a single `terraform apply` of cluster-config cannot plan them | Two-phase apply in the pipeline (templates, then the rest); T-TF5 |
| R-TF-2 | One state per customer and tier (up to ~1,000 tenant states) needs orchestration and drift detection across many states | Pipeline runs only changed instances (registry diff) plus a scheduled drift plan per state (Stage 7/8) |
| A-TF-1 | Machine types and sizes (Cloud SQL tier, MIG machine type, autoscaling limits) are placeholders from the capacity model | Replace with product sizing (Q22) |
| A-H-1 | Products expose `/healthz` and `/readyz`, run as a non-root user with a read-only root filesystem, and ship a `migrate` command in the image | Product team contract; checked in T-H1/T-H4 |
| A-H-2 | Cloud Run and MIG application versions are deployed by the pipeline (`gcloud run deploy` / Packer + Ansible image roll-out); Helm is used only for GKE products | Stage 7 workflows |
| A-S7-1 | `platform-tenants` holds `tenants/<customer>.yaml` with CODEOWNERS (account team + platform); both platform repositories read each other through the GitHub App (T-CI2) | Stage 7 |
| A-S7-2 | MIG products run `migrate` from the boot-time loader of the first instance of a new version, under a database lock (product contract, extends A-H-1) | Confirm with MIG product teams |
| A-S7-3 | `workflow_dispatch` / schedules count as `main`; the reviewed environments restrict branches to `main`, so other refs fail WIF | T-CI3 |
| R-S7-1 | GitHub concurrency groups are per repository: `platform-infra` and `platform-tenants` can start an apply of the same state together | The GCS state lock rejects the second; re-run (§1.5 of the Stage 7–8 doc) |
| R-S7-2 | The prd pre-release backup runs as `tf-prd` (cloudsql.admin), broader than needed | Same pipeline trust boundary; a custom backup-only role later |
| R-S7-3 | Actions pinned to release tags, not commit SHAs | T-CI1 |
| A-S8-1 | Non-prod is measured (99 %) but has no SLO objects or paging; 4xx responses count as good | Stage 8 |
| A-S8-2 | asia-south1 list prices ≈ us-central1 × 1.12 | T-CO1 |
| A-S8-3 | Workload sizing and usage in `cost/cost-model.yaml` are illustrative | T-CO2, Q22 |
| A-S8-4 | PITR clone throughput 600 GB/h | T-DR2 |
| R-S8-1 | The per-customer MIG floor (prd 3 VMs, non-prod 1 per environment) is ~26 % of cost at 500 × Baseline | Prefer Cohort/Shared for MIG products; review floors (B10) |
| R-S8-2 | Corruption restore (~221 min) is close to the 4 h RTO; a larger pool storage cap would break BC03 | BC03 recomputes on every capacity change; split pools earlier |
| R-S8-3 | Regional DR is designed and costed but not activated (Q10): interim region RPO 24 h / RTO 48 h | BC04 blocks activation until N1/D9/DR cells are ready |
| R-S8-4 | Per-customer SLIs of Shared/Cohort products need LB request logging (cost, sampling) | Logging cost in the estimate; T-SL2 |
