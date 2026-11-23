# Changelog

All changes are design changes or locally tested tooling; nothing has been deployed.

## Stages 7 and 8 – CI/CD, cost, capacity, SLOs and DR (2026-11-23)

### Stage 7 – CI/CD (implemented, locally tested; no workflow run against GitHub or GCP)
- `tools/cicd/planner.py` (PL01–PL05): affected stack instances, database gate and releases per change, apply order from `terraform/stacks.yaml`, promotion rule, offboarding guard, capacity gate; onboarding sequence per customer.
- `cicd/platform-workflows/` (13 reusable workflows + workspace action) and `cicd/repos/` (12 caller workflows in 8 repositories); `apply-pipeline.yml` / `pr-pipeline.yml` generated from the stack catalogue.
- `tools/cicd/workflows.py` (CW01–CW09): identity gates per repository and trigger against D6, least privilege, runner groups, pinning, rollback constructs, generated pipelines, product build coverage.
- `tools/cicd/tf.sh`, `tools/cicd/smoke.py`, drift CLI in `tools/monitoring/drift.py`, `ansible/packer/product.pkr.hcl`, `.github/workflows/ci.yml`, `requirements.txt`.
- K28: `groups-mgr-<tier>` gate also allows `platform-infra` (D6). MIG `ignore_changes = [version]` (A-H-2).

### Stage 8 – cost, capacity, SLOs, DR (implemented, locally tested)
- `cost/cost-model.yaml` + `tools/cost/model.py` (CO01–CO04) → `documentation/cost-estimate.md`; `tools/cost/capacity.py` (CP01–CP02, planner PL05).
- `slo/slos.yaml` + `tools/slo/observability.py` (SL01–SL06); `observability` stack (10th stack); uptime checks in the tenant stack; GKE cost allocation on.
- `slo/dr.yaml` + `tools/slo/dr.py` (BC01–BC06); `sql-pool` DR-replica and backup-location options (inactive until Q10).
- K27: metrics-scope projects renamed `plt-obs-<tier>-NN` in `fldr-platform/<tier>` (Stage 2 table, diagrams 01, 02, 06). IAM: monitoring admin/viewer, logging config writer, groups reader for drift.
- Docs: `stage-7-8-cicd-cost-slo.md`, `assignment-completion-summary.md`, traceability column, register T-CI1–6, T-CO1–2, T-SL1–6, T-DR1–5, A-S7-*, R-S7-*, A-S8-*, R-S8-*.
- Tests: 386 passing; `check_all` 26 steps, 0 findings.

## Stages 5 and 6 – Terraform and Helm (2026-11-23)

### Structure and interfaces
- `terraform/stacks.yaml` (9 stacks: state, identity, required IAM, creates, order) + `tools/iac/stacks.py` (SK01–SK05); `interfaces/helm-release.schema.json` (Terraform outputs + registry -> Helm values, every field with its producer).
- Bridges: `tools/iac/tfvars.py` (generated tfvars per stack instance, 21 files for the example) and `tools/iac/helmvalues.py` (values per release + render).

### Stage 5 – Terraform (implemented, statically checked; not run)
- 18 modules in `terraform/modules/`, 9 root stacks in `terraform/stacks/`; one state per stack instance (tenant and product states per customer/product per tier).
- `tools/iac/hclcheck.py` (HC01–HC07): scan, variables, module wiring, outputs, versions/backends, generated tfvars vs variables, forbidden content.
- Access matrix: grants the stacks need to apply (network/DNS/tag admin on host projects, load balancer/certificate admin on ingress projects, org firewall policy admin, logging config, Shared VPC host enablement, group creation, pool key rings, Binary Authorization policy editor) – 270 bindings, D3 checks pass; SK02 keeps them in sync.

### Stage 6 – Helm and Ansible (implemented, locally tested)
- `helm/charts/platform-lib` (library) + `helm/charts/payroll` + `helm/environments/`; `tools/helmrender` (Go text/template renderer, offline) renders all 8 releases; `tests/test_helm.py` checks D8 rules, schemas, contract, negative cases.
- `ansible/` (MIG products): bake-image and configure playbooks, base/app roles, dynamic inventory; `tests/test_ansible.py`.
- `examples/` ABC/XYZ Terraform inputs and Helm values / rendered manifests (`tools/iac/examples.py`, `tests/test_examples.py`).
- `documentation/stage-5-6-terraform-helm.md`; architecture checklist (Stages 5–6 closed); register T-TF1…T-TF6, T-H1…T-H4, T-AN1, R-TF-1/2, A-TF-1, A-H-1/2.
- Tests: 324 passing.

## Stage 4 – Networking, complete (2026-11-23)

### N1 IP address plan – locally tested
- `network/ip-plan.yaml`, `tools/network/ipam.py` (IP01–IP04) → `build/ip-plan.json`; `tests/test_network_ipam.py`.
- RFC 1918 only: prd 10.64.0.0/10, nonprd 10.128.0.0/10, one /11 per region (asia-south2 reserved for DR); per-cell GKE slots (prd 16, nonprd 48) with an equal-size Pod reserve range; Cloud Run /16, PSA /16, MIG /17 per tier; proxy-only and CI blocks reserved. Sized and checked against the capacity-model upper bound.
- D8 placeholder Cloud SQL ranges replaced by the PSA ranges (A-D8-1 closed); a test keeps them equal.

### N2 VPC, subnets, Shared VPC – locally tested
- `network/vpc.yaml`, `tools/network/vpc.py` (NW01–NW07) → `build/network-plan.json`: subnets per tier and per GKE cell, PSA, Shared VPC attachments (only projects with VPC workloads, each to its own tier), GKE / Cloud Run / MIG / Cloud SQL network settings, members of `grp-wl-netusers-<tier>` (service agents) and GKE host bindings; `tests/test_network_vpc.py`.
- Access matrix: `grp-wl-netusers-<tier>` Network User moved from the host project to the tier's subnets (`subnet:snet-<tier>-as1-*`), as deferred in D3.
- Register: T-N3…T-N7, A-N1-1…3, R-N1-1, R-N2-1, R-N2-2.
- Tests: 250 passing.

### N3 Firewall – locally tested
- `network/firewall.yaml`, `network/egress.yaml`, `tools/network/firewall.py` (FW01–FW07) → `build/firewall.json`; `tests/test_network_firewall.py`.
- Hierarchical `fw-org` (go-to-next for IAP, LB and internal ranges; deny everything else) and tier folder policies denying the other tier both ways; one global network firewall policy per VPC with secure tags, default-deny egress and one FQDN egress rule per product; no platform classic VPC rules.
- K26 (technical correction): Cloud Run cannot be targeted by tags in firewall policies, so Cloud Run egress is matched by subnet (R-N3-1). Architecture §5.2 and diagram 11 updated.
- D8 integration: `allow-internet-egress` NetworkPolicy for products with an allow-list (declared ports, public addresses only); KB03 updated.

### N4 DNS, ingress, egress – locally tested
- `network/edge.yaml`, `tools/network/edge.py` (IN01–IN07) → `build/edge.json`: public zones per product per tier with records generated from the registry, wildcard certificates, private zones for Private Google Access, GKE Gateways per product/env/cell, ALBs and URL maps with cross-project backends (host → customer project check, A6/X3), Cloud Armor (WAF, rate limit, UAT deny-by-default), Cloud NAT sized at the upper bound; `tests/test_network_edge.py`.

### N5 Consolidation – locally tested
- `documentation/stage-4-networking.md`; `network/quotas.yaml` + `tools/network/quotas.py` (B14 network part); diagram 11; architecture checklist (Stage 4 item closed); traceability (Stage 4 column); `check_all` runs N1–N5.
- Register: T-N8…T-N12, A-N3-1, A-N4-1…3, R-N3-1.

## Stage 3 – complete (2026-11-22 – 2026-11-23)

Status legend: **Proposed** (design only) · **Implemented** (written, statically checked) · **Locally tested** (automated tests run here) · **Cloud-tested** (run in GCP – none so far).

### D1 Tenant registry – locally tested
- `registry/schemas/` (schema v2.1), `registry/platform/inventory.yaml`, example products (payroll, crm, notify, ledger) and tenants (abc, xyz), `registry/README.md` (rules R01–R16).
- `tools/registry/` loader (rejects duplicate YAML keys), naming (K18), validator.
- Duplicate-entry observation fixed: duplicate keys (R01), duplicate tenant/product files (R04), duplicate deployments and derived-name collisions (R12); the old "identical entry is not a collision" behaviour removed.
- `scripts/validate_names.py` is now a wrapper around `tools/registry/naming.py`.

### D2 Identity derivation – locally tested
- `tools/identity/derive.py` → Terraform-ready identity plan (service accounts, Workload Identity, namespaces, MySQL databases and IAM users, connect-group memberships, individual project and resource IAM); `tools/identity/README.md`.
- Product schema: optional `database.readonly_identity`.
- Tests: 54 passing in total (`tests/test_registry.py`, `tests/test_naming.py`, `tests/test_identity.py`).

### D2 corrections (review of D2)
- **Shared/Cohort isolation made explicit:** every service account and Cloud SQL IAM user now carries `tenant_scope`, `isolation_boundary` (`identity-and-database` vs `application`) and `served_tenants`. The former test "no data grant crosses tenants" is scoped to Dedicated identities; new tests bound multi-tenant identities (own product, own registered pool and environment, own deployment's tenants only) and cover two customers on one Shared product, two in one Cohort, and different cohorts. No customer-level isolation is claimed for Shared/Cohort identities (ADR-006 rev. 3, application-level).
- **Product-owned pools registered and validated:** `inventory.yaml` → `product_sql_pools`; validator rule R17; the generator looks pools up instead of constructing names. 6 new registry tests.
- Tests: 67 passing.

### D3 Access-control matrix – locally tested
- `security/role-catalog.yaml`, `security/groups.yaml`, `security/access-matrix.yaml`, generated `security/access-matrix.md`, `security/README.md`.
- `tools/access/matrix.py`: expands `{tenant}`/`{product}`/`{nn}` templates from the registry and inventory (28 groups, 182 concrete bindings for the example registry) and checks AC01–AC12; explicit, reviewable `exception` field instead of hard-coded exemptions.
- K21 (technical correction): PAM grants IAM roles to the requester only and cannot grant group membership → DBA-admin access uses time-bound group membership with expiry after approval. Updated: identity model, database architecture §3.1, ADR-009, diagram 13.
- K22 (consistency): customer-support groups split into `-prd`/`-nonprd` so no group spans tiers. Updated: identity model, architecture document, diagram 10, registry README (R14).
- Tests: 91 passing (24 new in `tests/test_access.py`).

### D4 MySQL grants and isolation-test harness – locally tested (privilege model, not MySQL)
- `tools/db/grants.py`: per-pool idempotent bootstrap SQL (databases, per-database roles with escaped grant patterns, role membership, default roles, `MAX_USER_CONNECTIONS`), wildcard canaries, expected `SHOW GRANTS` set, static checks, `isotest-impersonation.json`.
- `tools/db/isotest.py`: ISO-01…ISO-10 against a connector interface; non-destructive probes with cleanup; per-tier split; report states the Shared/Cohort application boundary.
- `tests/fake_mysql.py` (privilege model), `tests/test_db_grants.py`, `tests/test_db_isotest.py`: generated grants pass; nine injected defects are each caught. A local test found and fixed a canary-naming bug (a prefixed canary is not matched by the unescaped pattern).
- Access matrix: `sa:isotest-<tier>@shr-cicd-<tier>` with resource-level `roles/iam.serviceAccountTokenCreator` on scope `sa-set:db-users-<tier>` (184 bindings, 0 findings). Risk R-D4-1.

### D5 Organisation and folder policies – proposed values, checker locally tested
- `security/org-policies.yaml` (25 constraints, 31 policies, approved folder tree), generated `security/org-policies.md`, `tools/policy/orgpolicy.py` (OP01–OP08), `tests/test_org_policies.py`.
- The checker caught two issues in the first draft (a no-op non-prod VPC-egress policy; prd/nonprd subnet lists are tier-scoped, not stricter/looser) – fixed with an explicit `tier_scoped` flag.

### D8 Kubernetes namespace baseline and policy constraints – locally tested (Rego not executed)
- `security/k8s-baseline.yaml`, `tools/k8s/baseline.py` (renders Namespace, SAs, RoleBindings, NetworkPolicies, ResourceQuota, LimitRange per namespace; cluster role `platform-tenant-edit`; Constraints with registry-derived parameters; checks KB01–KB06).
- `policies/k8s/src/*.rego` + `*_test.rego` (namespace baseline, HTTPRoute hostname = tenant (A6), allowed images by digest, tenant node separation), generated `policies/k8s/constraint-templates.yaml`, `tests/test_k8s_baseline.py`.
- Validation register: T-M9, T-M10, T-O1…T-O6, T-K19…T-K22; risks and assumptions R-D4-1, A-D4-1, A-D5-1, A-D8-1…3.
- Tests: 163 passing.

### D6 CI/CD identities and Workload Identity Federation – locally tested
- `security/cicd-identities.yaml`: WIF pool `ci-pool` (bootstrap-seed), GitHub provider pinned to the organisation id and the central reusable workflows for `prd`; Bitbucket provider defined but disabled (A6); composite `attribute.gate` (repository id : environment : ref class); repositories, GitHub environments, runner groups; authentication entry for every pipeline SA (WIF or attached Cloud Run job).
- `tools/cicd/federation.py` (CI01–CI09) → `build/wif-bindings.json`; `tests/test_cicd_federation.py`.
- Access matrix (gaps found while wiring the pipelines): `tf-org@bootstrap-seed` for the org stacks (implied by `tfstate-org`, no identity before); read-only `tf-plan-org/-prd/-nonprd` so PR plans never receive a write-capable identity; Terraform state bucket access per tier; `run.invoker` for `tf-<tier>` to start the bootstrap and isolation-test jobs. The first CI05 run flagged PR plans of both tiers sharing one gate – fixed with `plan-<tier>` environments.
- K24 (consistency): `deployer-<tier>` in ADR-010, architecture §5.1/§5.4 and diagrams 01, 02, 06, 09, 10 renamed to `deploy-<tier>` as in the identity model and access matrix (diagram 06 now names `tf-<tier>` for Terraform applies). SVG exports in `diagrams/rendered/` not re-exported (mermaid-cli unavailable here); the `.mmd` sources and the generated architecture document are current.

### D7 Privileged access – locally tested
- `security/privileged-access.yaml`: PAM entitlements (org admin, prod support write, per-product prod secret write), time-bound DBA-admin membership, break-glass accounts and procedure, `required_alerts` for D10.
- `tools/access/privileged.py` (PA01–PA07) → `build/pam-entitlements.json` (7 entitlements, one per resource); `tests/test_privileged_access.py`.
- Access matrix: security-audit as Cloud Identity manager of `grp-hum-dba-prd-admin` only (with recorded exception).
- K25 (consistency): Stage 2 described break-glass both as "two sealed accounts" and as "add a named person to the break-glass group"; reconciled as one mechanism (sealed non-federated super-admin accounts add a named person with expiry). Architecture §5.1 and identity model updated.

### D9 Secrets, keys and supply chain – locally tested
- `security/data-protection.yaml`, `tools/security/dataprotection.py` (DP01–DP08) → `build/data-protection.json` (9 keys, 16 secrets, 16 buckets, 8 Binary Authorization policies); `tests/test_data_protection.py`.
- Access matrix: product-conditioned `secretVersionAdder` (non-prod standing, prod via PAM); builder may create attestations on `attestor:shr-build/built-by-shr-build` (AC07 allows that scope).
- D5 additions (dry-run): `compute.trustedImageProjects` (shr-build) and `run.allowedBinaryAuthorizationPolicies` (prod); CMEK constraint validation renamed T-S1.
- K23 (technical correction): the Stage 2 isolation table said a mis-granted bucket role "needs key access too". CMEK decryption is performed by the service agent, so CMEK is not a second access check; it provides per-customer revocation (crypto-shredding). Architecture §3 table corrected.
- Validation register: T-W1…T-W5, T-P1…T-P3, T-S1…T-S6; risks and assumptions R-D6-1…3, R-D7-1/2, R-D9-1, A-D9-1/2.
- Tests: 203 passing.

### D10 Audit logging, security monitoring and alerts – locally tested (filters not run on real logs)
- `security/audit-monitoring.yaml`: Data Access logs (IAM credentials, STS, KMS, Secret Manager, Cloud SQL org-wide; Cloud Storage in prod folders), org aggregated sink to the locked `org-audit-locked` bucket in `shr-security`, notification channels, 14 log-based alert policies (all six D7 `required_alerts` plus SA keys, org policy changes, audit-config tampering, human secret reads, key destruction, out-of-pipeline IAM, `tf-org` use, isolation-test token minting).
- `tools/monitoring/audit.py` (AU01–AU07) → `build/monitoring.json`; `tools/monitoring/drift.py` (DR01 cross-tenant IAM, DR02 workload-group drift); `tests/test_audit_monitoring.py`.
- Found while writing the filters: Cloud Logging evaluates OR before AND; AU02 rejects filters that mix them without parentheses, and AL-AUDIT-CONFIG-CHANGE was corrected.
- Register: T-A1…T-A5, Q25, A-D10-1/2, R-D10-1…3.

### D11 Consolidation – locally tested
- `documentation/stage-3-security-implementation.md`: deliverables, connections, assignment mapping, personas, alerts, corrections (K21–K25), carried-forward items, validation order.
- Register consolidated: one Stage 3 risk and assumption table (D1–D10); R-D6-4 records the B1 decision (tier-wide prod deployer for now). `tests/test_registers.py` checks that every T-/R-/A- ID referenced anywhere is registered exactly once (it caught a reference to a PAM validation item that had never been registered).
- `tools/check_all.py` runs D1–D10 in dependency order.
- Updated: README, requirements traceability (Stage 3 column), security README, architecture checklist (Stage 3 item closed).
- Tests: 227 passing.

## Stage 2 final corrections – 2026-11-22 (naming and identity consistency)

### Added
- `registry/naming-rules.md` – registry schema v2.1 slug rules and derived-name length budget (K18).
- `scripts/validate_names.py` – naming validator with 13 boundary tests (13/13 pass locally).
- Identity model §4a – Cloud SQL mechanism 1 (project IAM policy groups) vs mechanism 2 (IAM group database authentication); 200-groups-per-instance budget (K20).

### Changed
- `database-architecture-mysql.md` §3 – corrected SA length calculation (customer ≤ 10, product ≤ 11; migration SA max 30); DBA row and authentication step reference the two mechanisms (K18, K20).
- `identity-and-groups-model.md` §1, §3, §4, §9, §10 – workload vs human role group wording; T-G2 mandatory (K19, K20).
- ADR-009 rev. 2 (decision 1 and 5), ADR-003 rev. 3 (decisions 4 and 7), architecture document §0/§3.1/§8.3, diagram 13, assumptions register (T-G2, T-G3, T-K18), review addendum.

## Stage 2 final reconciliation – 2026-11-22 (MySQL, groups, capacity)

### Added
- `documentation/database-architecture-mysql.md` – Cloud SQL for MySQL 8.4 design: privilege model, accounts, roles, hardening, bootstrap, mandatory isolation test ISO-01…10, migrations, pooling, restore, offboarding, MySQL vs PostgreSQL trade-offs (M1–M8).
- `documentation/identity-and-groups-model.md` – human / pipeline / workload identities, hybrid groups model, automation, review, revocation (G1–G5).
- ADR-011 Cloud SQL for MySQL 8.4.
- Diagram 13 – MySQL identities, accounts, roles and isolation gate.
- Assumptions A17–A18, questions Q22–Q24, validation-test register (T-M1…8, T-G1…5, T-N1/2, T-K1, T-L1), recommendations R17–R19.

### Changed
- ADR-003 → revision 3 (MySQL); ADR-004 (MySQL dedicated tier); ADR-006 → revision 3 (savings qualified, database-per-tenant on MySQL); ADR-009 → revision 2 (hybrid identity model).
- Capacity model → revision 2 and `scripts/capacity_model.py`: product groups and split rule, four pool constraints (tenants, connections, storage growth, 50,000-table limit), DR replicas, pool-project sharding, project categories, A16 sensitivity (C1–C3).
- Architecture document: workload SA naming includes the customer (M1), MySQL roles, groups naming, components, runtime text, registry/catalogue (`engine: mysql`, `major_version: "8.4"`, `pool_group`), bootstrap step, resource mapping, isolation table, identity section, §6.1/§6.3, ADR table, change log §8.3.
- Diagrams 02, 03, 04, 05, 06, 08, 10 (MySQL, SA names, groups).
- Review document: reconciliation banner and addendum (superseded: A3, X1, F6, parts of A4/F7, B5).
- Assumptions register (A5, A16, Q7, Q16 updated), requirements traceability.

## Stage 2 architecture review – 2026-11-22

Findings and evidence: [`documentation/stage-2-architecture-review.md`](documentation/stage-2-architecture-review.md).

### Added
- `documentation/stage-2-architecture-review.md` – feasibility, security-path, consistency and completeness review (findings A1–A7, B1–B17, K1–K17).
- `documentation/capacity-model.md` and `scripts/capacity_model.py` – variable-subscription capacity model (200/500 customers × 1–20 products) (A1).
- ADR-008 GKE cluster per environment and cells (A1).
- ADR-009 Fleet-wide IAM via Google groups (A2).
- ADR-010 Build/deploy separation, signed artifacts, state and runners per tier (A5).
- Assumptions A14–A16, open questions Q16–Q21; recommendations R13–R16.

### Changed
- ADR-003 → revision 2: product-group prod pools, sharded pool projects, PostgreSQL hardening baseline + cross-tenant denial test, group IAM, connection budget and edition dependency (A1–A4).
- ADR-006 → revision 2: product projects, names and registry fields for Shared/Cohort models (A7).
- ADR-002, ADR-004, ADR-005, ADR-007: `isolation_tier` rename, dedicated-tier non-prod note, cross-references (K2, K13).
- Architecture document: naming (env_tier / isolation_tier, new resource names), components, GKE/MIG text, registry schema v2, onboarding steps, mapping (cluster per environment), isolation table, security, scalability (§6 rewritten to the capacity model), ADR table, change log, checklist.
- Diagrams 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12 updated (each file carries a "Revised in Stage 2 review" note where applicable).
- Requirements traceability statuses.

### Fixed (consistency)
- K1 GKE ingress path in diagram 02 · K2 overloaded `tier` · K3 non-prod placement missing · K4 Shared/Cohort hosting missing · K5 VM images built on non-prod runner · K6 PGA VIP and Cloud Run tags · K7 VPC-SC vs masking flow · K8/K17 Cloud SQL estimates · K9 one cluster per tier · K10 pooling edition · K11 database isolation stated as default · K12 NetworkPolicy egress · K13 dedicated non-prod · K14 backup retention on offboarding · K15 naming gaps · K16 diagram 01 labels.

## Stage 2 – 2026-11-22
- Initial architecture document, 12 diagrams, ADR-001…007, assumptions register, traceability.
