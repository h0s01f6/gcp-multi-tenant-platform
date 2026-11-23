# Stage 3 – Security, identity and access control (consolidated)

Stage 3 turns the approved Stage 2 security architecture into implementation-ready configuration, generators and checks. It does not change the Stage 2 decisions; where Stage 3 found an error or inconsistency in them, the correction is listed in §6.

**Status legend** – *Proposed*: design/configuration values awaiting company input · *Implemented*: written and statically checked · *Locally tested*: automated tests run in this repository · *Cloud-tested*: run in GCP. **Nothing in Stage 3 is cloud-tested.** No GCP organisation, project, cluster or database was used.

## 1. Deliverables

| ID | Deliverable | Main files | Checker rules | Generated output (Terraform / pipeline input) | Status | GCP validation |
|---|---|---|---|---|---|---|
| D1 | Tenant registry and naming | `registry/`, `tools/registry/` | R01–R17 | – | Locally tested | T-K18 (real SA at 30 chars) |
| D2 | Identity derivation | `tools/identity/derive.py` | golden plan + isolation-boundary tests | `build/identity-plan.json` | Locally tested | T-M1, T-G1, T-G2 (**mandatory**), T-G4, T-G5 |
| D3 | Access-control matrix | `security/role-catalog.yaml`, `groups.yaml`, `access-matrix.yaml` → `access-matrix.md` | AC01–AC12 | `build/access-bindings.json` | Locally tested | T-G3, T-G6 |
| D4 | MySQL grants and isolation-test harness | `tools/db/` | static grant checks, ISO-01…ISO-10 | `build/sql/<pool>.sql`, expected grants, isotest impersonation bindings | Locally tested against a privilege **model**, not MySQL | T-M2, T-M3, T-M4, T-M9, T-M10 |
| D5 | Organisation and folder policies | `security/org-policies.yaml` → `org-policies.md`, `tools/policy/` | OP01–OP08 | `build/org-policy-effective.json` | Proposed values; checker locally tested | T-O1…T-O6, T-S2, T-S3 |
| D6 | CI/CD identities and Workload Identity Federation | `security/cicd-identities.yaml`, `tools/cicd/` | CI01–CI09 | `build/wif-bindings.json` | Proposed values; checker locally tested | T-W1…T-W5 |
| D7 | Privileged access (PAM, time-bound groups, break-glass) | `security/privileged-access.yaml`, `tools/access/privileged.py` | PA01–PA07 | `build/pam-entitlements.json` | Proposed values; checker locally tested | T-P1…T-P3 |
| D8 | Kubernetes namespace baseline and policy constraints | `security/k8s-baseline.yaml`, `tools/k8s/`, `policies/k8s/` | KB01–KB06 + 4 Rego templates | `build/k8s/<cell>/*.yaml`, `policies/k8s/constraint-templates.yaml` | Locally tested; **Rego not executed** | T-K1, T-K19…T-K22 |
| D9 | Secrets, keys and supply chain | `security/data-protection.yaml`, `tools/security/` | DP01–DP08 | `build/data-protection.json` | Proposed values; generator locally tested | T-S1…T-S6 |
| D10 | Audit logging, security monitoring and alerts | `security/audit-monitoring.yaml`, `tools/monitoring/` | AU01–AU07, drift DR01–DR02 | `build/monitoring.json` | Proposed values; checker and drift logic locally tested; **filters not run against real logs** | T-A1…T-A5 |
| D11 | Consolidation | this document, `documentation/assumptions-and-open-questions.md`, `tools/check_all.py`, `tests/test_registers.py` | register consistency | – | Locally tested | – |

```bash
python3 -m tools.check_all        # runs D1–D10 in dependency order; exit 0 only if every checker reports 0 findings
python3 -m pytest -q tests        # all automated tests
```

Local tooling limits: `opa`, `gator`, `terraform`, `kubectl`, MySQL and its Python drivers are not installed in this workspace and package installs are blocked, so Rego policies, Terraform and live SQL could not be executed. Their logic is exercised through Python tests where possible and recorded as validation items where not.

## 2. How the pieces connect

1. **Registry (D1)** is the only source of customers, products, versions and placement.
2. **Identity plan (D2)** derives every workload SA, Workload Identity binding, namespace, database, IAM database user, workload-group membership and per-resource grant from it.
3. **Access matrix (D3)** defines human and pipeline access by persona; templates expand from the registry. Every later deliverable reads it instead of redefining identities.
4. **D4** turns the plan into per-pool SQL and an isolation gate that blocks onboarding, promotion and deployment.
5. **D5** sets the guardrails at org and folder level; **D9** and **D10** check themselves against D5 (key projects, locations, Binary Authorization, trusted images).
6. **D6** says how each pipeline identity in D3 authenticates; **D7** says how each `jit` / `expiring` / `breakglass` grant in D3 is obtained and which alerts it needs; **D10** implements those alerts.
7. **D8** renders each namespace's baseline from D2 and the D3 `k8s:` grants.
8. **D11** tests that every validation, risk and assumption ID referenced anywhere is registered once.

## 3. Assignment security requirements → Stage 3

| Assignment item | Stage 3 implementation |
|---|---|
| Tenant identity, IAM, service accounts (§3) | D1 naming, D2 one SA per customer-product-environment, D3 groups only for non-data permissions |
| Namespaces, RBAC, NetworkPolicy (§3) | D8 baseline per namespace, created before any workload; RoleBindings from D3 |
| Secret Manager (§3, §4) | D9 per-customer secrets, CMEK in prod, values never in Git or Terraform state |
| Customer data isolation (§3, §7) | D4 database-per-customer-product grants + mandatory ISO-01…10 gate; D2 resource-level IAM; D10 DR01 cross-tenant drift check |
| Production access restrictions (§4, §8) | D3 no standing human write in prod (AC03); D7 PAM / time-bound access; D6 prod identities only from reviewed `prd` environment on `main` |
| Six personas (§8) | D3 personas (AC09); D7 elevation paths; D6 pipelines |
| Automation identities (§8, §12) | D6 WIF, no keys (D5), runner machines without grants |
| Org-level security policies (§8) | D5 |
| Vulnerability management / supply chain (§8, §12) | D9 build gates, attestation, Binary Authorization; D8 image policy |
| Audit and monitoring of security events (§8, §13) | D10 |

## 4. Personas → access paths (summary of D3, D6, D7)

| Persona | Standing | Elevated |
|---|---|---|
| Platform administrators | Org read | PAM `pam-org-admin` (2 h, security approval) |
| DevOps engineers | Non-prod operate (dev edit), prod read | PAM `pam-prd-support-write` (4 h) |
| Product development teams | Non-prod read for own product; non-prod secret versions for own product | PAM `pam-prd-secret-write-<product>` (1 h) |
| Customer-specific users | Read on that customer's namespaces/projects, per tier | – |
| Production support engineers | Prod read; DBA read-only | DBA admin via 4 h group membership (K21) |
| Automated pipelines | Per-tier identities via WIF (D6); attached job identities for DB bootstrap and isolation tests | – |
| Emergency | – | Break-glass (§5, D7) |

## 5. Security alerts (D10)

All alerts are Cloud Monitoring log-based alert policies in `shr-security`, evaluated on the locked org audit bucket (400 days, placeholder). Data Access logs are enabled for IAM credentials, STS, KMS, Secret Manager and Cloud SQL org-wide and for Cloud Storage in prod folders.

| Alert | Severity | Detects | Covers |
|---|---|---|---|
| AL-BG-LOGIN | page | Login by a break-glass account | D7, R-D7-2 |
| AL-BG-MEMBERSHIP | page | Change of `grp-hum-prd-breakglass` membership | D7 |
| AL-BG-USE | page | Human write at org/folder level (only possible via PAM or break-glass) | D7, R-D10-1 |
| AL-PAM-GRANT | ticket | PAM grant created/approved | D7 |
| AL-DBA-MEMBERSHIP | ticket | Change of `grp-hum-dba-prd-admin` membership | D7, R-D7-1 |
| AL-BINAUTHZ-BREAKGLASS | page | Deployment bypassing attestation (GKE / Cloud Run) | D9 |
| AL-ISOTEST-TOKEN | info | Token minting by the isolation-test identity (daily correlation with gate runs) | D4, R-D4-1 |
| AL-TF-ORG-USE | ticket | Any change by `tf-org` | D6, R-D6-2 |
| AL-SA-KEY-CREATED | page | Service-account key creation or upload | D5, D6 |
| AL-ORG-POLICY-CHANGE | page | Org policy change by anyone but `tf-org` | D5 |
| AL-AUDIT-CONFIG-CHANGE | page | Sink, bucket, exclusion, log view or Data Access config change | D10 |
| AL-SECRET-READ-HUMAN | page | Human reading a prod secret value | D9 |
| AL-KEY-DESTROY | page | CMEK key version disabled or destroyed | D9, K23 |
| AL-IAM-OUT-OF-PIPELINE | ticket | IAM change on tenant/platform projects not made by Terraform | D2, D3 |

Nightly drift checks: **DR01** cross-tenant IAM members (the Stage 2 "IAM grant crossing tenants" detection, which a log filter alone cannot express) and **DR02** workload-group membership vs the identity plan.

## 6. Corrections and gaps closed during Stage 3

| ID | Type | Change |
|---|---|---|
| K21 | Technical correction (D3) | PAM grants IAM roles only, not group membership → DBA admin uses time-bound group membership |
| K22 | Consistency (D3) | Customer-support groups split per tier |
| K23 | Technical correction (D9) | CMEK is not a second access check (the service agent decrypts); it gives per-customer revocation. Stage 2 isolation table corrected |
| K24 | Consistency (D6) | `deployer-<tier>` → `deploy-<tier>` in ADR-010, architecture and diagrams |
| K25 | Consistency (D7) | Two Stage 2 break-glass descriptions reconciled into one mechanism |
| D4 | Bug found by a test | Wildcard canary must not carry a prefix, or the unescaped pattern never matches it |
| D6 | Gap | `tf-org` (org stacks), read-only `tf-plan-<tier>` for PR plans, state-bucket access, `run.invoker` for DB jobs |
| D8 | Gap | `k8s/edit` maps to `platform-tenant-edit`, not built-in `edit` (which can delete NetworkPolicies) |
| D10 | Precision | Cloud Logging evaluates OR before AND; filters mixing both must use parentheses (AU02) |

## 7. Carried forward to later stages

| Stage | Input from Stage 3 |
|---|---|
| 4 Networking | Real PSA / subnet ranges replace `k8s-baseline.yaml` placeholders (A-D8-1); Shared VPC subnet policies (T-O5); Cloud Run VPC egress (T-O6) |
| 5 Terraform | Consumes `build/*.json` (identity plan, access bindings, grants, WIF bindings, PAM entitlements, keys/secrets/Binary Authorization, monitoring); GKE Binary Authorization mode (T-S4) |
| 6 Helm / Ansible | Chart constraints A-D8-3 (no SAs/NetworkPolicies/RBAC/quota in charts, images by digest, port `http`, explicit hostnames); Pod Security `restricted` (T-K22) |
| 7 CI/CD | Reusable workflows in `platform-workflows`, environments and runner groups from `cicd-identities.yaml`; isolation-test connector (T-M10); drift export jobs (T-A4) |
| 8 Operations | Alert runbooks, quarterly access review and break-glass drill (T-P3) |

## 8. Outstanding validation (summary)

The full register is in [`assumptions-and-open-questions.md`](assumptions-and-open-questions.md): 50 technical validation items (19 from Stage 2, 31 added in Stage 3), the open questions and the Stage 3 risk and assumption register. Only T-K18 passes locally, and even that still needs a real 30-character service account.

Suggested order in a GCP test organisation (each unblocks the next):

1. **Identity foundations:** T-G2 (mandatory), T-W1–T-W3 (federation), T-P1–T-P2 (PAM, expiring membership), T-A1 (Workspace audit sharing).
2. **Guardrails in dry-run:** T-O1–T-O6, T-S2, T-S3; then T-S1 before enforcing CMEK.
3. **Database isolation:** T-M1, T-M2, T-M9, T-M10, T-M3, T-M4 – the ISO gate must pass on real Cloud SQL before any customer data.
4. **Clusters:** T-K1, T-K19, T-K20, T-K21, T-K22, T-S4.
5. **Detection:** T-A2, T-A3 (with the T-P3 break-glass drill), T-A4, T-A5; T-S6 end to end.
