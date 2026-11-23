# Identity and groups model

> **Status:** Proposed (Stage 2 final reconciliation, 2026-11-22). Decision record: ADR-009 rev. 2. Feeds the Stage 3 access-control matrix.
> Review IDs: A2 (IAM policy limits), **G1–G5** (introduced here). Nothing here has been tested; tests are listed in §9.

## 1. The principle

> **Groups aggregate permissions. Individual service accounts remain the identities of workloads.**

- A **group** is used only where **all members genuinely need exactly the same permission**. It keeps shared IAM policies small (an allow policy holds at most 1,500 principals and 250 groups/domains, counting every appearance) and makes access easy to review.
- An **identity** (person or service account) is always individual. Audit logs record the individual SA or user, never "the group". So putting SAs into groups loses no auditability.
- **Workload groups never carry customer-specific data access** (clarified – review K19). They provide only common infrastructure permissions such as Cloud SQL connectivity, artifact pulls and subnet use. Anything that reaches one customer's data is granted to that customer's **individual** SA: bucket, secret, KMS key, Cloud Run invoker, MySQL database roles and grants, Workload Identity binding.
- **Human role groups may carry centrally approved, role-based privileges**, including database privileges for DBAs (diagnostics read-only, or time-bound admin through Privileged Access Manager). These are platform-wide operational roles approved by the security team, not customer-specific grants to an application.
- **No group may give one customer's application identity access to another customer's database.** Workload SAs are never members of a group that is added to a Cloud SQL instance as a database user, and no group holds a customer-specific database grant.

## 2. Identity categories

### A. Human identities (from the corporate IdP, synced to Cloud Identity / Google Workspace)

| Who | Group (illustrative names) | Scope | What it grants | Prod write? |
|---|---|---|---|---|
| Platform administrators | `grp-hum-platform-admins` | Organization (very few members) | Org/folder administration for exceptional changes; day-to-day changes go through pipelines | Only via pipeline or PAM |
| Production operators | `grp-hum-platform-prd-operators` | `fldr-*/prd` | Viewer, logs/metrics; **eligible** for PAM entitlements (time-bound write, approval required) | JIT only |
| Non-production operators | `grp-hum-platform-nonprd-operators` | `fldr-*/nonprd` | Viewer + limited operational roles; changes via PR | No |
| Security / audit | `grp-hum-security-audit` | Organization | Security reviewer, audit-log viewer, SCC viewer | No |
| DBAs | `grp-hum-dba-prd-ro`, `grp-hum-dba-prd-admin` (empty by default; time-bound membership with expiry after approval – K21), `grp-hum-dba-nonprd` | Pool projects | Cloud SQL viewer + **IAM group database authentication** with a diagnostics role (ro) or an admin role (JIT) | JIT only |
| Product developers | `grp-hum-product-<product>-dev` | Product's non-prod namespaces/services, product repos | Deploy via PR; logs/metrics for their product | No |
| Customer support | `grp-hum-cust-<cust>-support-prd` and `-nonprd` (two per customer, K22) | One group per tenant project – no group spans prod and non-prod | Viewer, log access for that customer only | No |
| Break-glass | `grp-hum-prd-breakglass` (normally empty) | Organization | Emergency admin; membership change and use both alert | Emergency |

### B. Pipeline identities (individual SAs; groups only where several SAs share a base permission)

| Purpose | Identity | Notes |
|---|---|---|
| Build and artifact publishing | `builder@shr-build` | Only writer of the `release` repository; signs artifacts |
| Terraform – non-prod | `tf-nonprd@shr-cicd-nonprd` | Infrastructure in non-prod folders; state bucket `tfstate-nonprd` |
| Terraform – prod | `tf-prd@shr-cicd-prd` | Only from GitHub environment `prd` on protected `main`; `tfstate-prd` |
| Application deploy – non-prod | `deploy-nonprd@shr-cicd-nonprd` | Helm / Cloud Run revisions / MIG templates in non-prod |
| Application deploy – prod | `deploy-prd@shr-cicd-prd` | As above for prod; later split per tenant (B1) |
| Ansible execution | `ansible-nonprd@…`, `ansible-prd@…` | OS Login via IAP to MIG VMs; scoped per run (B15) |
| Database bootstrap | `sqlboot-nonprd@plt-sql-nonprd-NN`, `sqlboot-prd@plt-sql-prd-NN` | IAM DB user with `cloudsqlsuperuser`; grants + isolation tests |
| Group membership automation | `groups-mgr-nonprd@…`, `groups-mgr-prd@…` | Set as **manager of specific groups only** (not a Workspace super admin) |

Pipeline groups: `grp-pl-prd-deployers` and `grp-pl-nonprd-deployers` hold the base permissions shared by all deployers of a tier (pull release artifacts, connect to clusters). They become useful when per-tenant prod deployers (B1) are introduced; tenant-specific write permissions stay on the individual deployer SA.

### C. Workload identities (always individual, one per customer-product-environment)

| Runtime | Identity | Example |
|---|---|---|
| GKE | KSA `payroll` in namespace `abc-payroll-prd` → Workload Identity → GSA | `abc-payroll-prd@t-abc-prd.iam.gserviceaccount.com` |
| Cloud Run | Service identity of the service `crm-prd` in `t-abc-prd` | `abc-crm-prd@t-abc-prd…` |
| Compute Engine MIG | Attached SA in the instance template | `abc-ledger-prd@t-abc-prd…` |
| Migration jobs | Separate SA | `abc-payroll-prd-mig@t-abc-prd…` |

- ABC Payroll Prod and XYZ Payroll Prod **never** share an identity; Dev, Stage, UAT and Prod have separate identities.
- SA IDs include the customer because Cloud SQL for MySQL derives the database username from the SA's local part (M1).
- Shared/Cohort products are the documented exception: one product identity per environment (or cohort) serves many customers, and isolation is the application's responsibility (ADR-006 rev. 3).

## 3. Workload groups (only identical, non-data permissions)

| Group | Members | Permission | Why identical for all members |
|---|---|---|---|
| `grp-wl-sqlconn-prd-NN` | App and migration SAs whose databases live in pool project `plt-sql-prd-NN` | `cloudsql.client` + `cloudsql.instanceUser` on `plt-sql-prd-NN` (project-level – Cloud SQL has no per-instance IAM) | It only lets an identity **attempt** a login; MySQL then allows only that account's own database |
| `grp-wl-sqlconn-nonprd-NN` | Same for non-prod pool projects | Same | Same |
| `grp-wl-ar-readers-prd` | Prod pull identities (GKE node SAs, Cloud Run service agents, MIG SAs) | Reader on the `release` repository | All prod runtimes pull the same signed artifacts |
| `grp-wl-ar-readers-nonprd` | Non-prod pull identities | Reader on `release` (+ `snapshot` for Dev) | Same |
| `grp-wl-netusers-prd` / `-nonprd` | Service agents of service projects (e.g. Cloud Run service agent) | Network User on the tier's runtime subnets, Network Viewer on the host project | Using a subnet grants no access to other tenants' resources |

**Workload groups grant infrastructure permissions only – never customer-specific database privileges.**

**How this maps to the example names in the request:** `grp-payroll-prod-db` becomes `grp-wl-sqlconn-prd-NN`, scoped to the **pool project** that holds the Payroll product group's pools. It grants only the ability to connect to that pool project's instances. It does **not** give all Payroll prod SAs the same database access; that is decided per account inside MySQL.

## 4a. Two different ways a group meets Cloud SQL (review K20)

| | Mechanism 1 – group in the **project IAM policy** | Mechanism 2 – group added to the **Cloud SQL instance as an IAM database user** (IAM group authentication) |
|---|---|---|
| What is configured | `roles/cloudsql.client` + `roles/cloudsql.instanceUser` granted to the group on the pool project | The group is created as a database user on the instance; MySQL privileges are granted to that group account |
| What members get | Permission to reach the instance through a connector and to **attempt** an IAM login – on every instance in the project | Login **and** the group's database privileges; Cloud SQL creates each member's database account at first login |
| Database privileges come from | Each identity's **own** MySQL account and roles (created individually) | The **group's** grants, inherited identically by every member |
| Used for | **Workload SAs**: `grp-wl-sqlconn-<tier>-NN` | **Human DBAs only**: `grp-hum-dba-prd-ro`, `grp-hum-dba-prd-admin`, `grp-hum-dba-nonprd` |
| Why | Keeps shared IAM policies small while every tenant keeps its own database grants | Role-based human access with central approval; leavers lose access by group removal |
| Documented constraints | IAM allow-policy limits (1,500 principals, 250 groups/domains per policy) | **Maximum 200 IAM groups per instance**; an individual IAM account cannot be added for a user or SA that belongs to a group already added to the same instance; membership changes take about 15 minutes to propagate |
| Validation | **T-G2 (mandatory):** an individually created IAM SA database user can log in when `cloudsql.instanceUser` comes only through group membership. Google's Cloud SQL how-to states that all members of a group granted the Instance User role can log in to instances in the project, but this combination must still be proven before onboarding relies on it | T-G3 |

**Rules that follow from this:**
1. `grp-wl-*` groups are used **only** in mechanism 1 and are never added to an instance as database users.
2. Human DBA groups never contain service accounts. Workload SAs are never members of a mechanism-2 group, so their individual accounts remain valid (avoids the "individual account in a group on the same instance" conflict).
3. **Group-count budget per instance:** prod pools carry 2 DBA groups (`-ro`, `-admin`), non-prod pools 1 (`grp-hum-dba-nonprd`); at most 1 more is reserved for a security-audit read-only group. That is **≤ 3 of the 200 allowed**. Per-customer support groups (up to ~500) are **never** added to instances; customer-support staff get database access only through an approved DBA path, never per customer.
4. ISO-09 (grant drift) also checks that the instance's group users are exactly the approved DBA groups.

## 4. Can Cloud Identity groups be used for …?

| Use | Supported? | Use it here? |
|---|---|---|
| Google Cloud IAM permissions | Yes – groups (including SAs as members) are IAM principals | **Yes** – all fleet-wide, non-data grants (§3) and all human access (§2A) |
| Cloud SQL for MySQL IAM database authentication | Yes – two mechanisms (§4a). **Mechanism 1** (IAM policy) grants connect/login permission; **mechanism 2** (IAM group authentication) also gives members the group's database privileges (max 200 groups per instance; about 15 minutes propagation) | Mechanism 1 for workloads (connect only). Mechanism 2 for **human DBAs only** – never for tenant workloads, because every member would inherit identical database privileges |
| Group-based database privilege assignment | Yes, through mechanism 2 | Only for centrally approved human roles that are identical for all members (DBA diagnostics, time-bound DBA admin, read-only audit); never customer-specific |
| Human access management | Yes; combine with Privileged Access Manager for time-bound prod write | **Yes** |
| Pipeline access management | Yes | Sparingly – a few SAs; groups only for shared base permissions of deployers |

## 5. Comparison

| Model | IAM policy size at 500 customers | Isolation | Operations | Verdict |
|---|---|---|---|---|
| Individual bindings for every SA | Exceeds 1,500 principals in pool, artifact and network projects (capacity model T7) | Fine-grained | Many bindings; slow reviews | Not feasible |
| Groups for everything (incl. data and DB privileges) | Tiny | **Broken** – members get identical data access across customers | Simple | Rejected |
| **Hybrid: groups for identical non-data permissions; individual SAs for data, DB and runtime identity** | Tiny shared policies; per-customer policies stay in tenant projects | Preserved | Group membership automated from the registry | **Recommended** |

## 6. How groups are organised

1. **Environment tier first** – no group spans prod and non-prod (hard boundary).
2. **Then category** – `hum`, `pl`, `wl` – a group never mixes people and workloads.
3. **Then purpose/role** – e.g. `sqlconn`, `ar-readers`, `prd-operators`.
4. **Then scope where needed** – pool project (`-NN`), product (`product-<product>`) or customer (`cust-<cust>`).

**Group-count growth (illustrative, 500 customers × 20 products):** ~1,000 customer-support groups (prd + non-prd) + ~40 product groups + ~15 platform/DBA/security groups + ~10–30 workload groups (one per pool project and tier) ≈ **600 groups**. Each shared allow policy references only a handful of groups. Per-customer groups are bound **inside that customer's projects**, so no single policy approaches the 250-group limit.

**Consequence for log access (G4):** per-customer log views in a central GKE log bucket would put up to 500 customer groups (each with a view condition) into one project policy, which breaks the 250-group limit. **Correction:** route each customer's GKE workload logs with log sinks to a log bucket in that customer's tenant project, and bind `grp-hum-cust-<cust>-support-<tier>` there. The default is 200 sinks per project, increasable to 4,000, so one sink per customer per cluster project is possible with a quota increase. This replaces the log-view approach in B5.

## 7. Membership automation and review

- **Workload/pipeline groups:** managed only by the project factory (Terraform `google_cloud_identity_group_membership`) from the tenant registry, using `groups-mgr-<tier>` as group **manager** of those specific groups.
- **Human groups:** fed from the corporate IdP (joiner/mover/leaver). Prod admin and DBA-admin groups stay empty and are reached only through PAM entitlements.
- **Drift detection (nightly):** compare each workload group's members with the registry; alert on any unexpected member, any human in a `wl` group, any SA in a `hum` group, and any membership change of break-glass groups.
- **Access review:** quarterly attestation by group owners (security team for platform groups, account owners for customer-support groups); evidence kept.
- **Change control:** adding a member to a `wl` group is part of the onboarding PR; nobody adds members by hand.

## 8. Offboarding and emergency revocation

| Event | Actions | Effective |
|---|---|---|
| Customer / product offboarded | Remove SAs from `wl` groups, delete DB accounts (ISO-10), delete SAs, delete `grp-hum-cust-<cust>-support-prd/-nonprd` | Pipeline-driven |
| Employee leaves | IdP deprovisioning removes them from all groups; PAM grants expire | IdP-driven |
| Compromised workload SA | **Disable the SA** + MySQL `ACCOUNT LOCK` + kill sessions (immediate); then remove from groups | Seconds to minutes |
| Compromised human | Suspend in IdP, end PAM grants, remove from groups; for DBA group auth, lock their MySQL account because membership changes take about 15 minutes to reach Cloud SQL | Minutes |
| Emergency access | One of the two sealed break-glass (Cloud Identity super-admin) accounts adds a named person to `grp-hum-prd-breakglass` with an expiry (alerts); two-person rule; reviewed after use (D7) | Immediate, audited |

## 9. Controls that groups do *not* provide

Groups simplify administration; they do **not** isolate tenants. Workload groups provide only common infrastructure permissions; human DBA groups provide approved role-based access. These controls must still be enforced individually:
- **Project level:** two tenant projects per customer; prod and non-prod separated.
- **Service-account level:** one SA per customer-product-environment; resource-level IAM on buckets, secrets, KMS keys, Cloud Run invoker and backend services; Workload Identity bound per namespace.
- **Database level:** per-database roles, escaped grants, no global privileges, isolation test ISO-01…10.
- **Network level:** separate prod/non-prod VPCs, NetworkPolicy default-deny, LB-only firewall for MIGs, Gateway hostname policy.
- **Pipeline level:** WIF conditions, protected environments, runner groups, per-tier state.

## 10. Validation tests that need a GCP test project

| ID | What to prove |
|---|---|
| T-G1 | Propagation time from adding an SA to a group until (a) IAM permission works and (b) Cloud SQL group authentication works (documented about 15 minutes for (b)) |
| T-G2 (**mandatory gate before onboarding uses mechanism 1**) | An individually created IAM SA database user can log in when `cloudsql.instanceUser` comes **only** through group membership in the project policy; also that removing the SA from the group blocks new logins. If it fails, the fallback in the capacity model applies |
| T-G3 | IAM group authentication (mechanism 2) for human DBA groups on MySQL 8.4: inherited privileges, first-login account creation, revocation on removal, group count per instance reported correctly against the 200 limit |
| T-G4 | SAs and service agents as members of Cloud Identity / Workspace groups; `groups-mgr` can manage only its own groups |
| T-G5 | Behaviour near policy limits (250 groups, conditions) – confirms the G4 log-routing decision |
