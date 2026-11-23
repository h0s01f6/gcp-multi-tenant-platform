# Architecture diagrams

GitHub renders the Mermaid diagrams below directly from source. The `.mmd` files are the editable source of truth; SVG exports are retained in `rendered/` for external viewing.

<a id="01-resource-hierarchy"></a>
## 01-resource-hierarchy — Resource Hierarchy

```mermaid
%% 01 - GCP resource hierarchy (environment-first)
%% Status: PROPOSED baseline, revised in Stage 2 review (A1, A5, A7, K2, K16); Stage 8 K27 (plt-obs-<tier>-NN).
%% Project IDs get a random suffix in reality, e.g. t-abc-prd-x7k2. NN = shard number (01, 02 ...).
flowchart TB
  ORG["Organization: example.com<br/>org policies: no SA keys, no default network,<br/>allowed regions, uniform bucket access, OS Login"]

  ORG --> FB["fldr-bootstrap"]
  ORG --> FS["fldr-shared"]
  ORG --> FN["fldr-network"]
  ORG --> FP["fldr-platform"]
  ORG --> FT["fldr-tenants"]

  FB --> P_SEED["bootstrap-seed<br/>state buckets: tfstate-org, tfstate-nonprd, tfstate-prd<br/>(separate IAM per tier)<br/>WIF pool for GitHub OIDC"]

  FS --> P_BLD["shr-build<br/>build runners, builder SA,<br/>signing / attestations"]
  FS --> P_ART["shr-artifacts<br/>Artifact Registry: release (build-only write),<br/>snapshot (Dev only)"]
  FS --> P_CIN["shr-cicd-nonprd<br/>runner pool + deploy-nonprd"]
  FS --> P_CIP["shr-cicd-prd<br/>runner pool + deploy-prd"]
  FS --> P_SEC["shr-security<br/>audit log bucket (locked), SCC exports"]

  FN --> P_NHP["net-host-prd<br/>Shared VPC host: vpc-prd"]
  FN --> P_NHN["net-host-nonprd<br/>Shared VPC host: vpc-nonprd"]

  FP --> FPP["prd"]
  FP --> FPN["nonprd"]
  FPP --> P_GKEP["plt-gke-prd<br/>gke-prd-as1-01 (+ cells -02 ...)<br/>only platform cells in this project"]
  FPP --> P_SQLP["plt-sql-prd-NN<br/>prod pools per product group / product<br/>e.g. sql-prd-payroll-01, sql-prd-crm-01"]
  FPP --> P_INGP["plt-ingress-prd<br/>global external ALBs + Cloud Armor<br/>(Cloud Run and MIG products)"]
  FPP --> P_PRODP["p-product-prd<br/>only for Shared / Cohort products"]
  FPP --> P_OBP["plt-obs-prd-NN<br/>metrics scope, SLOs, alerts (K27)<br/>sharded at ~375 projects"]
  FPN --> P_GKEN["plt-gke-nonprd<br/>gke-dev-as1-01, gke-stg-as1-01,<br/>gke-uat-as1-01 (+ cells)"]
  FPN --> P_SQLN["plt-sql-nonprd-NN<br/>sql-dev-NN, sql-stg-NN, sql-uat-NN"]
  FPN --> P_INGN["plt-ingress-nonprd"]
  FPN --> P_PRODN["p-product-nonprd<br/>only for Shared / Cohort products"]
  FPN --> P_OBN["plt-obs-nonprd-NN<br/>metrics scope (K27)"]

  FT --> FTP["prd<br/>strict prod policies + prod access groups"]
  FT --> FTN["nonprd"]
  FTP --> T_ABCP["t-abc-prd<br/>tag isolation_tier=standard"]
  FTP --> T_XYZP["t-xyz-prd<br/>tag isolation_tier=standard"]
  FTP --> T_BIGP["t-bigco-prd<br/>tag isolation_tier=dedicated<br/>own GKE cluster + own Cloud SQL"]
  FTN --> T_ABCN["t-abc-nonprd<br/>Dev + Stage + UAT"]
  FTN --> T_XYZN["t-xyz-nonprd<br/>Dev + Stage + UAT"]
  FTN --> T_BIGN["t-bigco-nonprd<br/>uses shared non-prod tiers by default (Q18)"]

  P_NHP -. "subnets shared with service projects in" .-> FPP
  P_NHP -. "subnets shared with service projects in" .-> FTP
  P_NHN -. "subnets shared with service projects in" .-> FPN
  P_NHN -. "subnets shared with service projects in" .-> FTN

  classDef prd fill:#fde2e1,stroke:#c0392b,color:#000
  classDef nonprd fill:#e1ecfd,stroke:#2c6fbb,color:#000
  classDef shared fill:#eeeeee,stroke:#555,color:#000
  class FPP,FTP,P_GKEP,P_SQLP,P_INGP,P_PRODP,T_ABCP,T_XYZP,T_BIGP,P_NHP,P_CIP,P_OBP prd
  class FPN,FTN,P_GKEN,P_SQLN,P_INGN,P_PRODN,T_ABCN,T_XYZN,T_BIGN,P_NHN,P_CIN,P_OBN nonprd
  class FB,FS,FN,FP,FT,P_SEED,P_ART,P_SEC,P_BLD shared
```

- [Mermaid source](01-resource-hierarchy.mmd) · [SVG export](rendered/01-resource-hierarchy.svg)

<a id="02-platform-architecture"></a>
## 02-platform-architecture — Platform Architecture

```mermaid
%% 02 - Overall multi-tenant platform architecture (one region shown: asia-south1)
%% Status: PROPOSED baseline, revised in Stage 2 review (A1, A2, A5, K1) and final reconciliation (MySQL, groups). DR region is in diagram 12.
flowchart LR
  USERS["Customer end users<br/>abc.payroll.example.com<br/>abc.crm.example.com"]
  ENG["Engineers<br/>(corporate IdP SSO)"]

  subgraph SHARED["Shared services (fldr-shared, fldr-bootstrap)"]
    direction TB
    GIT["GitHub org<br/>app repos, platform-tenants registry,<br/>platform-infra, platform-charts, platform-ansible"]
    BLD["shr-build<br/>builds, scans, signs images,<br/>charts, VM images"]
    AR["shr-artifacts<br/>release repo: written only by shr-build<br/>snapshot repo: Dev only"]
    CIN["shr-cicd-nonprd<br/>ephemeral runners<br/>deploy-nonprd (via WIF)"]
    CIP["shr-cicd-prd<br/>ephemeral runners<br/>deploy-prd (via WIF, env prd only)"]
    STN["tfstate-nonprd"]
    STP["tfstate-prd"]
    OBS["plt-obs-prd-NN / plt-obs-nonprd-NN<br/>metrics scopes, Managed Prometheus,<br/>dashboards, SLOs, alerting"]
    SEC["shr-security<br/>org audit log sink, SCC"]
    GRP["Cloud Identity groups (ADR-009 rev. 2)<br/>humans grp-hum-*, pipelines grp-pl-*,<br/>workloads grp-wl-sqlconn / ar-readers / netusers<br/>(identical non-data permissions only)"]
  end

  subgraph PRD["PRODUCTION tier"]
    direction TB
    NETP["net-host-prd: Shared VPC vpc-prd<br/>subnets, Cloud NAT, PGA,<br/>private services access for Cloud SQL"]
    INGP["plt-ingress-prd<br/>global external ALB + Cloud Armor<br/>Cloud Run and MIG products"]
    subgraph GKEP_G["plt-gke-prd"]
      GWP["GKE Gateway<br/>(creates its own global ALB)"]
      GKEP["gke-prd-as1-01 Autopilot<br/>namespaces per customer-product"]
    end
    SQLP["plt-sql-prd-NN<br/>Cloud SQL for MySQL 8.4 pools (HA)<br/>sql-prd-payroll-01, sql-prd-crm-01<br/>database + role per customer-product"]
    subgraph TPRD["Tenant projects: t-abc-prd, t-xyz-prd ..."]
      TRUN["Cloud Run services"]
      TMIG["Regional MIGs"]
      TDATA["GCS buckets, Secret Manager,<br/>per-workload SAs, KMS keyring"]
    end
    PPRD["p-product-prd<br/>Shared / Cohort products"]
    DED["t-bigco-prd (dedicated tier)<br/>own GKE cluster + own Cloud SQL"]
  end

  subgraph NPRD["NON-PRODUCTION tier"]
    direction TB
    NETN["net-host-nonprd: Shared VPC vpc-nonprd"]
    INGN["plt-ingress-nonprd"]
    GKEN["plt-gke-nonprd<br/>gke-dev-as1-01, gke-stg-as1-01,<br/>gke-uat-as1-01 (each with own Gateway)"]
    SQLN["plt-sql-nonprd-NN<br/>MySQL 8.4 pools sql-dev-NN, sql-stg-NN, sql-uat-NN"]
    TNON["Tenant projects: t-abc-nonprd, t-xyz-nonprd ...<br/>Cloud Run, MIGs, buckets, secrets, SAs, keys"]
  end

  USERS --> GWP --> GKEP
  USERS --> INGP
  USERS -. "UAT testers only" .-> INGN
  INGP --> TRUN
  INGP --> TMIG
  INGN --> TNON
  USERS -. "UAT testers only" .-> GKEN

  GKEP -- "Workload Identity as tenant SA" --> TDATA
  GKEP -- "IAM DB auth" --> SQLP
  TRUN --> SQLP
  TRUN --> TDATA
  TMIG --> SQLP
  TMIG --> TDATA
  GKEN --> SQLN
  GKEN --> TNON

  GIT -- "app repos" --> BLD -- "signed release artifacts" --> AR
  GIT -- "registry PR merged" --> CIN
  GIT -- "approved prod change" --> CIP
  CIN -- "Terraform / Helm / gcloud / Ansible" --> NPRD
  CIP -- "Terraform / Helm / gcloud / Ansible" --> PRD
  CIN --- STN
  CIP --- STP
  AR -. "pull by digest" .-> PRD
  AR -. "pull" .-> NPRD
  GRP -. "fleet-wide grants" .-> SQLP

  PRD -. "metrics, logs" .-> OBS
  NPRD -. "metrics, logs" .-> OBS
  PRD -. "audit logs" .-> SEC
  NPRD -. "audit logs" .-> SEC
  ENG -- "read-only by default,<br/>JIT elevation for prod" --> OBS

  classDef prd fill:#fde2e1,stroke:#c0392b,color:#000
  classDef nonprd fill:#e1ecfd,stroke:#2c6fbb,color:#000
  classDef shared fill:#eeeeee,stroke:#555,color:#000
  class INGP,GKEP,GWP,SQLP,TRUN,TMIG,TDATA,DED,NETP,CIP,STP,PPRD prd
  class NETN,INGN,GKEN,SQLN,TNON,CIN,STN nonprd
  class GIT,BLD,AR,OBS,SEC,GRP shared
```

- [Mermaid source](02-platform-architecture.mmd) · [SVG export](rendered/02-platform-architecture.svg)

<a id="03-gke-runtime"></a>
## 03-gke-runtime — Gke Runtime

```mermaid
%% 03 - GKE-based product runtime (Payroll in production)
%% Two customers, two different versions, one shared Autopilot cluster.
%% Revised in Stage 2 review: A2 (group IAM), A6 (hostname policy), K12 (egress).
%% Final reconciliation: Cloud SQL for MySQL 8.4, customer-unique SA names (M1), per-database roles (M2).
flowchart LR
  U1["ABC users<br/>abc.payroll.example.com"]
  U2["XYZ users<br/>xyz.payroll.example.com"]

  subgraph EDGE["Edge (global)"]
    ALB["Global external ALB<br/>created by GKE Gateway<br/>Cloud Armor WAF + rate limits<br/>cert *.payroll.example.com"]
  end

  subgraph CL["plt-gke-prd / gke-prd-as1-01 (Autopilot, regional, private nodes, Dataplane V2)"]
    direction TB
    subgraph GWNS["ns: gateway-infra (platform-owned)"]
      GW["Gateway gw-payroll-prd<br/>allowedRoutes: namespaces labelled product=payroll<br/>admission policy: route hostnames must match<br/>the namespace tenant and env labels"]
    end
    subgraph NSA["ns: abc-payroll-prd  labels tenant=abc product=payroll env=prd"]
      RA["HTTPRoute host abc.payroll.example.com"]
      HA["Helm release abc-payroll-prd<br/>chart payroll 2.0.2, image payroll@sha256 digest"]
      PA["Deployment payroll x3 pods across zones<br/>HPA 3..12, PDB minAvailable 2<br/>readiness + liveness probes"]
      KA["KSA payroll (app)<br/>KSA payroll-migrate (pre-upgrade Job)"]
      NPA["NetworkPolicy: default deny,<br/>allow from gateway, allow egress to<br/>kube-dns, GKE metadata server,<br/>Cloud SQL + Google APIs only"]
      QA["ResourceQuota + LimitRange"]
    end
    subgraph NSX["ns: xyz-payroll-prd  labels tenant=xyz product=payroll env=prd"]
      RX["HTTPRoute host xyz.payroll.example.com"]
      HX["Helm release xyz-payroll-prd<br/>chart payroll 1.5.3, image payroll@sha256 digest"]
      PX["Deployment payroll x2 pods"]
      KX["KSA payroll"]
      NPX["NetworkPolicy (same baseline)"]
    end
  end

  subgraph TA["t-abc-prd"]
    GSA_A["GSA abc-payroll-prd@t-abc-prd<br/>(+ abc-payroll-prd-mig for migrations)"]
    SM_A["Secret Manager payroll-prd-*"]
    GCS_A["Bucket abc-payroll-prd-data"]
    KMS_A["KMS kr-abc-prd-as1 / payroll-prd"]
  end
  subgraph TX["t-xyz-prd"]
    GSA_X["GSA xyz-payroll-prd@t-xyz-prd"]
    SM_X["Secret Manager payroll-prd-*"]
    GCS_X["Bucket xyz-payroll-prd-data"]
  end
  subgraph SQL["plt-sql-prd-01 / sql-prd-payroll-01 (Cloud SQL for MySQL 8.4, HA)<br/>no global privileges for tenant accounts, isolation test ISO-01..10"]
    DBA["database abc_payroll<br/>account abc-payroll-prd: role r_abc_payroll_app<br/>account abc-payroll-prd-mig: role r_abc_payroll_ddl"]
    DBX["database xyz_payroll<br/>account xyz-payroll-prd: role r_xyz_payroll_app"]
  end

  U1 --> ALB
  U2 --> ALB
  ALB --> GW
  GW --> RA --> PA
  GW --> RX --> PX
  HA -. "renders" .-> PA
  HX -. "renders" .-> PX
  PA --- KA
  PX --- KX
  KA == "Workload Identity:<br/>KSA impersonates GSA" ==> GSA_A
  KX == "Workload Identity" ==> GSA_X
  GSA_A --> SM_A
  GSA_A --> GCS_A
  GCS_A -. "CMEK" .-> KMS_A
  GSA_A -- "Auth Proxy, automatic IAM DB auth<br/>(connect via grp-wl-sqlconn-prd-01),<br/>grants only on abc_payroll" --> DBA
  GSA_X --> SM_X
  GSA_X --> GCS_X
  GSA_X -- "grants only on xyz_payroll" --> DBX
  PA -. "blocked by NetworkPolicy" .-x PX

  classDef abc fill:#fff3cd,stroke:#b8860b,color:#000
  classDef xyz fill:#d4edda,stroke:#2e7d32,color:#000
  class NSA,RA,HA,PA,KA,NPA,QA,GSA_A,SM_A,GCS_A,KMS_A,DBA abc
  class NSX,RX,HX,PX,KX,NPX,GSA_X,SM_X,GCS_X,DBX xyz
```

- [Mermaid source](03-gke-runtime.mmd) · [SVG export](rendered/03-gke-runtime.svg)

<a id="04-cloudrun-runtime"></a>
## 04-cloudrun-runtime — Cloudrun Runtime

```mermaid
%% 04 - Cloud Run-based product runtime (CRM in production)
%% Each customer's service lives in the customer's own tenant project.
%% Final reconciliation: MySQL 8.4 pool, customer-unique SA names (M1).
flowchart LR
  U1["ABC users<br/>abc.crm.example.com"]
  U2["XYZ users<br/>xyz.crm.example.com"]

  subgraph ING["plt-ingress-prd"]
    ALB["Global external ALB + Cloud Armor<br/>URL map: host rule per customer<br/>cert *.crm.example.com"]
  end

  subgraph TA["t-abc-prd"]
    BSA["backend service bs-crm-prd<br/>+ serverless NEG (asia-south1)"]
    RUNA["Cloud Run service crm-prd<br/>ingress: internal + load balancer only<br/>revision crm-prd-00042 = image crm 3.1.0<br/>min 1, max 20 instances, concurrency 80"]
    SAA["service identity abc-crm-prd@t-abc-prd<br/>MySQL account abc-crm-prd"]
    SMA["Secret Manager crm-prd-* (mounted as env/volume)"]
    GCSA["Bucket abc-crm-prd-files (CMEK)"]
  end

  subgraph TX["t-xyz-prd"]
    BSX["backend service bs-crm-prd<br/>+ serverless NEG"]
    RUNX["Cloud Run service crm-prd<br/>revision crm-prd-00017 = image crm 3.0.5"]
    SAX["service identity xyz-crm-prd@t-xyz-prd<br/>MySQL account xyz-crm-prd"]
    SMX["Secret Manager crm-prd-*"]
    GCSX["Bucket xyz-crm-prd-files"]
  end

  subgraph NET["net-host-prd / vpc-prd"]
    SUB["subnet snet-prd-as1-run<br/>Direct VPC egress, network tags<br/>run-crm"]
  end

  subgraph SQL["plt-sql-prd-01 / sql-prd-crm-01 (MySQL 8.4, HA)"]
    DBA["database abc_crm<br/>role r_abc_crm_app"]
    DBX["database xyz_crm<br/>role r_xyz_crm_app"]
  end

  OTHER["Another internal service<br/>(caller)"]

  U1 --> ALB
  U2 --> ALB
  ALB -- "cross-project backend reference" --> BSA --> RUNA
  ALB -- "cross-project backend reference" --> BSX --> RUNX
  RUNA --- SAA
  RUNX --- SAX
  SAA --> SMA
  SAA --> GCSA
  SAX --> SMX
  SAX --> GCSX
  RUNA -- "Direct VPC egress" --> SUB
  RUNX -- "Direct VPC egress" --> SUB
  SUB -- "private IP, IAM DB auth" --> DBA
  SUB -- "private IP, IAM DB auth" --> DBX
  OTHER -- "ID token, needs roles/run.invoker<br/>on that one service" --> RUNA
  RUNA -. "no invoker grant: 403" .-x RUNX

  classDef abc fill:#fff3cd,stroke:#b8860b,color:#000
  classDef xyz fill:#d4edda,stroke:#2e7d32,color:#000
  class BSA,RUNA,SAA,SMA,GCSA,DBA abc
  class BSX,RUNX,SAX,SMX,GCSX,DBX xyz
```

- [Mermaid source](04-cloudrun-runtime.mmd) · [SVG export](rendered/04-cloudrun-runtime.svg)

<a id="05-mig-runtime"></a>
## 05-mig-runtime — Mig Runtime

```mermaid
%% 05 - Compute Engine MIG-based product runtime
%% "Ledger" is an ILLUSTRATIVE VM-based product (not part of the ABC/XYZ Payroll/CRM example).
%% Revised in Stage 2 review: A5 (images built in shr-build, not on a non-prod runner).
flowchart LR
  U["ABC users<br/>abc.ledger.example.com"]

  subgraph BUILD["Build (shr-build + shr-artifacts)"]
    PK["Packer + Ansible playbook<br/>bakes OS hardening + ledger 4.2.1"]
    IMG["Image family ledger<br/>image img-ledger-4-2-1-20261120<br/>scanned + signed, shared via grp-wl-ar-readers"]
  end

  subgraph ING["plt-ingress-prd"]
    ALB["Global external ALB + Cloud Armor"]
  end

  subgraph TA["t-abc-prd"]
    BS["backend service bs-ledger-prd<br/>health check GET /healthz"]
    IT_OLD["instance template<br/>it-ledger-prd-4-2-0"]
    IT_NEW["instance template<br/>it-ledger-prd-4-2-1<br/>machine e2-standard-4, no public IP<br/>SA abc-ledger-prd@t-abc-prd<br/>metadata: tenant=abc env=prd<br/>config=secret ledger-prd-config"]
    MIG["Regional MIG mig-ledger-prd<br/>3 zones, autoscale 3..9 on CPU/LB util<br/>autohealing on /healthz<br/>rolling update maxSurge 1 maxUnavailable 0"]
    VM1["vm-1 zone a"]
    VM2["vm-2 zone b"]
    VM3["vm-3 zone c"]
    SA["SA abc-ledger-prd@t-abc-prd"]
    SM["Secret Manager ledger-prd-*"]
    GCS["Bucket abc-ledger-prd-data"]
    SNAP["(only if stateful disks)<br/>snapshot schedule"]
  end

  subgraph SQL["plt-sql-prd-01 / sql-prd-ledger-01 (MySQL 8.4)"]
    DB["database abc_ledger<br/>account abc-ledger-prd"]
  end

  subgraph OPS["Operations access"]
    ANS["Ansible controller (shr-cicd-prd)<br/>config drift + one-off ops"]
    IAP["IAP TCP forwarding<br/>+ OS Login (2FA, no SSH keys in metadata)"]
  end

  PK --> IMG --> IT_NEW
  U --> ALB --> BS --> MIG
  IT_OLD -. "previous version, kept for rollback" .-> MIG
  IT_NEW -- "rolling update target" --> MIG
  MIG --> VM1
  MIG --> VM2
  MIG --> VM3
  VM1 --- SA
  VM2 --- SA
  VM3 --- SA
  SA -- "startup: fetch config" --> SM
  SA --> GCS
  SA -- "IAM DB auth" --> DB
  ANS --> IAP --> VM2
  VM3 -.- SNAP
```

- [Mermaid source](05-mig-runtime.mmd) · [SVG export](rendered/05-mig-runtime.svg)

<a id="06-onboarding-workflow"></a>
## 06-onboarding-workflow — Onboarding Workflow

```mermaid
%% 06 - New customer subscribes to a product: request to handover
%% Example: new customer "def" subscribes to Payroll (GKE). Versions pinned per environment.
%% Revised in Stage 2 review: per-env placement (A1, A7), groups (A2), hostname policy (A6).
%% Final reconciliation: MySQL roles, customer-unique SAs (M1), isolation test ISO-01..10 as a gate.
sequenceDiagram
  autonumber
  actor REQ as Authorised requester<br/>(customer onboarding team)
  participant REG as GitHub platform-tenants<br/>(tenant registry)
  participant VAL as CI: validate job<br/>(nonprod runner)
  actor APR as Approvers<br/>(CODEOWNERS)
  participant TFN as Terraform apply<br/>(tf-nonprd, deploy-nonprd)
  participant DBJ as DB bootstrap job<br/>(Cloud Run job per tier in plt-sql-*)
  participant DEP as Deploy step<br/>(Helm / Cloud Run / MIG)
  participant MON as Monitoring<br/>(plt-obs-*)
  participant TFP as Prod pipeline<br/>(tf-prd, deploy-prd, protected env)

  REQ->>REG: PR adds tenants/def.yaml (tier, products, versions per env, owners)
  REG->>VAL: trigger on PR
  VAL->>VAL: schema check, naming rules, product exists in catalogue
  VAL->>VAL: version exists in Artifact Registry and is not blocked by scan
  VAL->>VAL: placement per environment: GKE cell and SQL pool with headroom (customer affinity)
  VAL->>VAL: hostnames and resource names derived from tenant slug only
  VAL->>REG: comment terraform plan for t-def-nonprd and t-def-prd
  APR->>REG: review plan and approve (platform team, plus product owner)
  REG->>TFN: merge to main triggers non-prod apply
  TFN->>TFN: project factory creates t-def-nonprd (labels, tags, Shared VPC attach, budgets)
  TFN->>TFN: SAs def-payroll-dev/stg/uat (+ -mig), buckets, secrets placeholders, KMS keyring
  TFN->>TFN: add workload SAs to grp-wl-sqlconn-nonprd-NN of their pool project (connect only)
  TFN->>TFN: namespaces on gke-dev/stg/uat cells with RBAC, quota, NetworkPolicy first
  TFN->>TFN: MySQL databases def_payroll on the placed sql-dev/stg/uat pools + IAM SA accounts (app, mig)
  TFN->>DBJ: per-database roles, escaped grants, default roles, MAX_USER_CONNECTIONS
  DBJ->>DBJ: SHOW GRANTS equals registry, then isolation test ISO-01..10 (gate)
  TFN->>MON: alert policies, dashboards, uptime checks labelled tenant=def
  TFN->>DEP: deploy Dev with version from def.yaml
  DEP->>DEP: helm upgrade --install def-payroll-dev (chart and image pinned)
  DEP->>MON: smoke tests + health checks
  MON-->>REG: Dev healthy, status posted on PR or ticket
  Note over REG,DEP: Promotion = new PR that sets stg (then uat) version.<br/>Each promotion repeats validate, plan, approve, deploy, verify.
  REQ->>REG: PR sets prd version (must equal a version that passed UAT for def)
  REG->>TFP: approval in GitHub protected environment prd (2 approvers, change window)
  TFP->>TFP: create t-def-prd, SAs, buckets, keys, namespace def-payroll-prd, database def_payroll on its prod pool (+ hardening test)
  TFP->>DEP: deploy Prod (progressive rollout)
  DEP->>MON: health checks, SLO burn alerts armed
  MON-->>REQ: handover: URLs, dashboard links, access groups, runbook link
```

- [Mermaid source](06-onboarding-workflow.mmd) · [SVG export](rendered/06-onboarding-workflow.svg)

<a id="07-lifecycle-operations"></a>
## 07-lifecycle-operations — Lifecycle Operations

```mermaid
%% 07 - Day-2 lifecycle: add product, upgrade version, offboard customer
%% All three start with a PR to the tenant registry. Nothing is changed by hand.
%% Revised in Stage 2 review: per-env placement (A7), retention note (K14).
flowchart TB
  subgraph ADD["A. Existing customer ABC adds product CRM"]
    direction TB
    A1["PR: add crm block to tenants/abc.yaml<br/>runtime cloudrun, versions per env"] --> A2["Validate + plan<br/>(projects already exist: only new resources;<br/>placement per env: pool with headroom)"]
    A2 --> A3["Apply non-prod: SAs crm-dev/stg/uat,<br/>databases abc_crm on dev/stg/uat pools,<br/>buckets, secrets, Cloud Run services"]
    A3 --> A4["Deploy Dev, verify"] --> A5["Promote Stage then UAT by PR"]
    A5 --> A6["Prod PR + approval: crm-prd in t-abc-prd,<br/>abc_crm on its prod pool, URL map host rule"]
  end

  subgraph UPG["B. Upgrade Payroll for XYZ only: 1.5.3 to 2.0.2"]
    direction TB
    U1["shr-build publishes chart + image 2.0.2<br/>(scanned, signed, release notes, DB migration notes)"] --> U2["PR: xyz.yaml payroll.dev = 2.0.2"]
    U2 --> U3["CI deploys only xyz-payroll-dev<br/>(Helm diff shows a single release)"]
    U3 --> U4["DB migration runs as pre-upgrade job<br/>against xyz_payroll only"]
    U4 --> U5{"Healthy?"}
    U5 -- "no" --> U6["helm rollback xyz-payroll-dev<br/>restore DB if migration was not backward compatible"]
    U5 -- "yes" --> U7["Promote stg, uat, then prd by PR<br/>prd: on-demand backup before migration"]
    U7 --> U8["ABC stays on 2.0.2 already, other<br/>customers untouched: separate releases"]
  end

  subgraph OFF["C. Offboard customer XYZ"]
    direction TB
    O1["PR: set xyz.yaml status = offboarding<br/>+ contract end date + data handling choice"] --> O2["Disable ingress host rules, scale workloads to zero"]
    O2 --> O3["Final export to customer, if contract requires<br/>(encrypted, signed URL, time-limited)"]
    O3 --> O4["Retention hold: keep backups for the agreed period<br/>(compliance decision, not technical)"]
    O4 --> O5["PR: remove tenant. Terraform destroys namespaces,<br/>Cloud Run, MIGs, drops xyz_* databases, SAs<br/>NOTE: pooled backups keep xyz data until<br/>backup retention expires (Q19)"]
    O5 --> O6["Projects t-xyz-prd / t-xyz-nonprd deleted<br/>(30-day recovery window), KMS keys scheduled for destruction"]
    O6 --> O7["Remove dashboards, alerts, labels from cost reports.<br/>Audit log retained centrally"]
  end
```

- [Mermaid source](07-lifecycle-operations.mmd) · [SVG export](rendered/07-lifecycle-operations.svg)

<a id="08-abc-xyz-example"></a>
## 08-abc-xyz-example — Abc Xyz Example

```mermaid
%% 08 - Worked example: ABC and XYZ, Payroll (GKE) and CRM (Cloud Run), all four environments
%% Versions are illustrative. Each box is owned by exactly one customer unless marked SHARED.
%% Revised in Stage 2 review: one GKE cluster per environment (ADR-008), pool project names, group IAM.
%% Final reconciliation: MySQL 8.4 pools, SA IDs include the customer (M1).
flowchart TB
  subgraph NP["NON-PROD tier"]
    direction LR
    subgraph GKEN["SHARED: plt-gke-nonprd (one cluster per environment)"]
      direction TB
      CDEV["gke-dev-as1-01<br/>abc-payroll-dev v2.1.0<br/>xyz-payroll-dev v2.0.2"]
      CSTG["gke-stg-as1-01<br/>abc-payroll-stg v2.0.3<br/>xyz-payroll-stg v1.5.4"]
      CUAT["gke-uat-as1-01<br/>abc-payroll-uat v2.0.3<br/>xyz-payroll-uat v1.5.4"]
    end
    subgraph TAN["t-abc-nonprd"]
      direction TB
      RA_N["Cloud Run<br/>crm-dev v3.2.0<br/>crm-stg v3.1.1<br/>crm-uat v3.1.1"]
      SA_AN["SAs abc-payroll-dev/stg/uat,<br/>abc-crm-dev/stg/uat (+ -mig)"]
      BK_AN["Buckets abc-payroll-ENV-data,<br/>abc-crm-ENV-files,<br/>abc-nonprd-masked-ingest"]
      SM_AN["Secrets payroll-ENV-*, crm-ENV-*<br/>KMS kr-abc-nonprd-as1"]
    end
    subgraph TXN["t-xyz-nonprd"]
      direction TB
      RX_N["Cloud Run<br/>crm-dev v3.1.1<br/>crm-stg v3.0.5<br/>crm-uat v3.0.5"]
      SA_XN["SAs xyz-payroll-dev/stg/uat,<br/>xyz-crm-dev/stg/uat (+ -mig)"]
      BK_XN["Buckets xyz-PRODUCT-ENV-*,<br/>xyz-nonprd-masked-ingest"]
      SM_XN["Secrets + KMS kr-xyz-nonprd-as1"]
    end
    subgraph SQLN["SHARED: plt-sql-nonprd-01 (MySQL 8.4)"]
      direction TB
      DEV["sql-dev-01 (zonal)<br/>abc_payroll, abc_crm,<br/>xyz_payroll, xyz_crm"]
      STG["sql-stg-01 (zonal)<br/>same four databases"]
      UAT["sql-uat-01 (HA, Q15)<br/>same four databases"]
    end
  end

  subgraph PR["PROD tier"]
    direction LR
    subgraph GKEP["SHARED: plt-gke-prd / gke-prd-as1-01"]
      direction TB
      PA["abc-payroll-prd  v2.0.2"]
      PX["xyz-payroll-prd  v1.5.3"]
    end
    subgraph TAP["t-abc-prd"]
      direction TB
      RA_P["Cloud Run crm-prd v3.1.0"]
      SA_AP["SAs abc-payroll-prd, abc-crm-prd (+ -mig),<br/>masker-prd"]
      BK_AP["Buckets abc-payroll-prd-data,<br/>abc-crm-prd-files, abc-prd-exports"]
      SM_AP["Secrets + KMS kr-abc-prd-as1"]
    end
    subgraph TXP["t-xyz-prd"]
      direction TB
      RX_P["Cloud Run crm-prd v3.0.5"]
      SA_XP["SAs xyz-payroll-prd, xyz-crm-prd (+ -mig),<br/>masker-prd"]
      BK_XP["Buckets xyz-payroll-prd-data,<br/>xyz-crm-prd-files, xyz-prd-exports"]
      SM_XP["Secrets + KMS kr-xyz-prd-as1"]
    end
    subgraph SQLP["SHARED: plt-sql-prd-01 (MySQL 8.4)"]
      direction TB
      PPAY["sql-prd-payroll-01 (HA)<br/>abc_payroll, xyz_payroll"]
      PCRM["sql-prd-crm-01 (HA)<br/>abc_crm, xyz_crm"]
    end
  end

  CDEV -- "Workload Identity (ABC ns)" --> SA_AN
  CDEV -- "Workload Identity (XYZ ns)" --> SA_XN
  RA_N --- SA_AN
  RX_N --- SA_XN
  SA_AN -- "grants on abc_* only" --> SQLN
  SA_XN -- "grants on xyz_* only" --> SQLN
  PA -- "Workload Identity" --> SA_AP
  PX -- "Workload Identity" --> SA_XP
  RA_P --- SA_AP
  RX_P --- SA_XP
  SA_AP -- "abc_* only" --> SQLP
  SA_XP -- "xyz_* only" --> SQLP

  SA_AP == "masker-prd: one-way,<br/>write-only to masked-ingest" ==> BK_AN
  SA_XP == "masker-prd: one-way" ==> BK_XN

  SA_AN -. "DENIED: no IAM on t-xyz-*" .-x BK_XN
  SA_AN -. "DENIED: non-prod has no prod access" .-x BK_AP

  classDef abc fill:#fff3cd,stroke:#b8860b,color:#000
  classDef xyz fill:#d4edda,stroke:#2e7d32,color:#000
  classDef shared fill:#eeeeee,stroke:#555,color:#000
  class RA_N,SA_AN,BK_AN,SM_AN,PA,RA_P,SA_AP,BK_AP,SM_AP abc
  class RX_N,SA_XN,BK_XN,SM_XN,PX,RX_P,SA_XP,BK_XP,SM_XP xyz
  class DEV,STG,UAT,PPAY,PCRM,CDEV,CSTG,CUAT shared
```

- [Mermaid source](08-abc-xyz-example.mmd) · [SVG export](rendered/08-abc-xyz-example.svg)

<a id="09-prod-to-nonprod-data-flow"></a>
## 09-prod-to-nonprod-data-flow — Prod To Nonprod Data Flow

```mermaid
%% 09 - Controlled data movement: ABC Payroll Prod to ABC UAT (masked)
%% One direction only. Non-prod identities never receive read access to prod data.
%% Revised in Stage 2 review (K7): when the prod VPC-SC perimeter is enforced, this write needs one explicit egress rule.
sequenceDiagram
  autonumber
  actor OWN as ABC data owner<br/>(approver)
  participant REG as platform-tenants repo<br/>data-refresh request
  participant PRDP as Prod pipeline<br/>(deploy-prd)
  participant SQLP as sql-prd-payroll-01<br/>database abc_payroll
  participant EXP as Bucket abc-prd-exports<br/>(t-abc-prd, CMEK, 7-day lifecycle)
  participant MSK as Cloud Run job mask-payroll<br/>SA masker-prd@t-abc-prd
  participant ING as Bucket abc-nonprd-masked-ingest<br/>(t-abc-nonprd)
  participant NPP as Non-prod pipeline<br/>(deploy-nonprd)
  participant UAT as sql-uat-01<br/>database abc_payroll

  OWN->>REG: approve PR: refresh abc payroll uat from prd (masking profile payroll-v2)
  REG->>PRDP: merged request triggers prod-side job
  PRDP->>SQLP: export database abc_payroll only (serverless export, no load on primary)
  SQLP->>EXP: write dump object
  PRDP->>MSK: start job with masking profile payroll-v2
  MSK->>EXP: read dump (masker-prd has read on this bucket only)
  MSK->>MSK: apply rules: hash IDs, fake names, shift dates, null bank details,<br/>Sensitive Data Protection scan as a safety net
  MSK->>MSK: verification: fail the job if any column still matches a sensitive infoType
  MSK->>ING: write masked dump (objectCreator only, cannot read or list)
  ING-->>NPP: object finalize event
  NPP->>UAT: import into abc_payroll (replace), re-apply grants
  NPP-->>OWN: completion report: row counts, masking report, audit log links
  Note over EXP,ING: Prod export auto-deleted by lifecycle rule.<br/>No path exists for xyz data: masker-prd@t-abc-prd has no IAM on t-xyz-*.<br/>Future VPC-SC: egress rule allows only masker-prd to this one ingest bucket.
```

- [Mermaid source](09-prod-to-nonprod-data-flow.mmd) · [SVG export](rendered/09-prod-to-nonprod-data-flow.svg)

<a id="10-identity-access"></a>
## 10-identity-access — Identity Access

```mermaid
%% 10 - Identity and access: humans, pipelines, workloads
%% Authentication = who you are (IdP, OIDC token, Workload Identity). Authorisation = what you may do (IAM, RBAC, DB grants).
%% Revised in Stage 2 review: A2 (groups for fleet grants), A5 (WIF conditions, build identity).
%% Final reconciliation: hybrid groups model (ADR-009 rev. 2) - groups for identical non-data permissions, individual SAs.
flowchart LR
  subgraph HUM["Human identities"]
    direction TB
    IDP["Corporate IdP<br/>(Okta / Entra ID: to be confirmed)<br/>MFA enforced"]
    CI_ID["Cloud Identity<br/>SAML SSO + group sync<br/>(or Workforce Identity Federation)"]
    G1["grp-hum-platform-admins"]
    G2["grp-hum-platform-nonprd-operators"]
    G3["grp-hum-product-payroll-dev<br/>grp-hum-product-crm-dev"]
    G4["grp-hum-cust-abc-support-prd / -nonprd<br/>grp-hum-cust-xyz-support-prd / -nonprd"]
    G5["grp-hum-platform-prd-operators<br/>grp-hum-dba-prd-ro (IAM group DB auth)"]
    BG["Break-glass accounts (2)<br/>hardware keys, sealed, alert on use"]
  end

  subgraph CICD["Pipeline identities"]
    direction TB
    GH["GitHub Actions OIDC token<br/>claims: repo, ref, environment"]
    WIF["WIF pool in bootstrap-seed<br/>provider condition: repository_id allowlist<br/>prod binding: environment = prd AND ref = main"]
    DN["deploy-nonprd@shr-cicd-nonprd"]
    DP["deploy-prd@shr-cicd-prd<br/>only from environment prd<br/>on protected main branch"]
    BLDR["builder@shr-build<br/>only identity that writes release artifacts"]
  end

  subgraph PAMB["Just-in-time elevation"]
    PAM["Privileged Access Manager<br/>entitlement prod-support-write<br/>max 4h, approval + justification"]
  end

  subgraph SCOPES["Where access is granted (folder / project / resource)"]
    direction TB
    S_ORG["Organization"]
    S_NONPRD["fldr-tenants/nonprd + fldr-platform/nonprd"]
    S_PRD["fldr-tenants/prd + fldr-platform/prd"]
    S_TEN["Single-tenant resources<br/>buckets, secrets, databases,<br/>log view abc, dashboard abc"]
  end

  subgraph WL["Workload identities (one per customer-product-env)"]
    direction TB
    K["GKE KSA payroll in ns abc-payroll-prd"] --> GSA["abc-payroll-prd@t-abc-prd"]
    CR["Cloud Run crm-prd"] --> CRSA["abc-crm-prd@t-abc-prd"]
    VM["MIG mig-ledger-prd"] --> VMSA["abc-ledger-prd@t-abc-prd"]
    WG["grp-wl-sqlconn-prd-01<br/>(connect permission only,<br/>no data access)"]
  end

  IDP --> CI_ID --> G1 & G2 & G3 & G4 & G5
  G1 -- "org admin roles (few people)" --> S_ORG
  G2 -- "editor-equivalent via CI only,<br/>viewer for humans" --> S_NONPRD
  G2 -- "viewer" --> S_PRD
  G3 -- "deploy via PR, logs + metrics viewer" --> S_NONPRD
  G4 -- "viewer on own customer only" --> S_TEN
  G5 -- "viewer + eligible for PAM" --> S_PRD
  G5 --> PAM -- "temporary grant" --> S_PRD
  BG -. "emergency only" .-> S_ORG

  GH --> WIF --> DN
  WIF --> DP
  WIF --> BLDR
  DN -- "create and deploy" --> S_NONPRD
  DP -- "create and deploy" --> S_PRD
  GSA -- "own bucket, secrets, database only" --> S_TEN
  GSA -. "member of" .-> WG
```

- [Mermaid source](10-identity-access.mmd) · [SVG export](rendered/10-identity-access.svg)

<a id="11-network-security"></a>
## 11-network-security — Network Security

```mermaid
%% 11 - Network isolation and traffic controls (production shown; non-production is an identical, separate VPC)
%% vpc-prd and vpc-nonprd are NOT peered and NOT connected: no network path between tiers.
%% Revised in Stage 2 review (K6): private.googleapis.com until VPC-SC.
%% Stage 4: IP plan, per-cell subnets, firewall layering (N3), Cloud Run egress matched by subnet (K26).
flowchart TB
  NET_IN["Internet"]
  ADMIN["Engineer laptop"]

  subgraph EDGE["Edge"]
    ARMOR["Cloud Armor policy<br/>OWASP rules, rate limit,<br/>geo / IP allowlists for UAT"]
    ALB["Global external ALBs<br/>(GKE Gateway + plt-ingress-prd)<br/>TLS via Certificate Manager"]
  end

  subgraph HOST["net-host-prd: vpc-prd (Shared VPC)"]
    direction TB
    HFW["Hierarchical firewall policies<br/>fw-org: IAP, LB/health checks, 10.0.0.0/8 go to next; deny all else<br/>fw-tier-prd (prd folders): deny 10.128.0.0/10 both ways"]
    NFW["Network firewall policy fwp-prd (secure tags)<br/>IAP SSH to wl=mig only; LB to wl=mig / wl=gke-node :8080<br/>deny MIG VM-to-VM; egress: PSA :3307, PGA :443,<br/>intra-cluster, per-product FQDN; default deny egress"]
    subgraph SUBS["Subnets in asia-south1 (vpc-prd 10.64.0.0/10, region 10.64.0.0/11)"]
      S1["snet-prd-as1-gke-prd-NN (one per cell)<br/>nodes /22 from 10.82.0.0/16<br/>Pods /17 (+/17 reserve) from 10.64.0.0/12<br/>Services /20 from 10.80.0.0/15"]
      S2["snet-prd-as1-run 10.83.0.0/16<br/>Cloud Run Direct VPC egress"]
      S3["snet-prd-as1-mig 10.85.0.0/17<br/>MIG VMs, no public IPs"]
      S4["proxy-only 10.85.128.0/23<br/>reserved, not created"]
      S5["psa-prd-01 10.84.0.0/16<br/>Cloud SQL private IPs"]
    end
    NAT["Cloud NAT nat-prd-as1 (static IPs)<br/>+ FQDN egress rules per product<br/>(secure tags for MIG, Pod ranges for GKE,<br/>run subnet for Cloud Run – K26)"]
    PGA["Private Google Access<br/>private.googleapis.com now,<br/>restricted.googleapis.com once VPC-SC is enforced"]
  end

  subgraph K8S["Inside gke-prd-as1-01"]
    NP1["NetworkPolicy per namespace:<br/>default-deny ingress + egress"]
    NP2["allow ingress from gateway-infra only"]
    NP3["allow egress: kube-dns, Cloud SQL IP,<br/>Google APIs, same namespace"]
  end

  subgraph RUN["Cloud Run services"]
    RIN["ingress = internal-and-cloud-load-balancing<br/>no public run.app access"]
    RIAM["roles/run.invoker granted per service"]
  end

  subgraph PERIM["VPC Service Controls (recommended, Phase 6, dry-run first)"]
    VSC["Perimeter around prod tenant + plt-sql-prd-NN projects<br/>(one egress rule for the masking job write)<br/>blocks data exfiltration to outside projects"]
  end

  NET_IN --> ARMOR --> ALB
  ALB -- "GKE NEGs, MIG backends" --> HFW
  ALB -- "serverless NEG" --> RIN
  HFW --> S1
  HFW --> NFW --> S3
  S1 --> K8S
  RUN -- "Direct VPC egress (outbound only)" --> S2
  S1 & S2 & S3 --> S5
  S1 & S2 & S3 --> NAT
  S1 & S2 & S3 --> PGA
  ADMIN -- "IAP TCP forwarding + OS Login" --> HFW
  PGA --> VSC
```

- [Mermaid source](11-network-security.mmd) · [SVG export](rendered/11-network-security.svg)

<a id="12-dr-topology"></a>
## 12-dr-topology — Dr Topology

```mermaid
%% 12 - High availability and disaster recovery (production)
%% Regions are ASSUMPTION A4 (asia-south1 primary, asia-south2 DR). RPO/RTO are placeholder targets (A8).
flowchart LR
  USERS["Users"] --> GLB["Global external ALBs<br/>backends in both regions<br/>health-based failover"]

  subgraph R1["asia-south1 (primary, active)"]
    direction TB
    G1["gke-prd-as1-01 (+ cells) Autopilot<br/>regional: pods spread over 3 zones"]
    C1["Cloud Run services<br/>multi-zone by default"]
    M1["Regional MIGs<br/>3 zones, autohealing"]
    SQL1["Cloud SQL HA pools (plt-sql-prd-NN)<br/>primary + standby in 2 zones<br/>automated backups + PITR"]
  end

  subgraph R2["asia-south2 (DR, pilot light)"]
    direction TB
    G2["gke-prd-as2-01 Autopilot<br/>created, no tenant pods<br/>(Helm releases applied on failover)"]
    C2["Cloud Run services deployed<br/>min instances 0"]
    M2["MIGs from same templates<br/>target size 0"]
    SQL2["Cloud SQL cross-region<br/>read replicas (async, count as instances)<br/>promote on regional failure"]
  end

  subgraph GLOBALDATA["Region-independent data"]
    GCS["Prod buckets: dual-region or<br/>replicated (to be confirmed per region pair)"]
    BKP["Backup vault / exported backups<br/>in second region, immutable retention"]
    AR["Artifact Registry multi-region repo"]
    TFS["Terraform state bucket (dual-region, versioned)"]
  end

  GLB --> G1
  GLB --> C1
  GLB --> M1
  GLB -. "failover" .-> G2
  GLB -. "failover" .-> C2
  GLB -. "failover" .-> M2
  SQL1 -- "async replication" --> SQL2
  SQL1 -- "daily backups" --> BKP
  G1 & C1 & M1 --> SQL1
  G2 & C2 & M2 -.-> SQL2
  G1 & C1 & M1 --> GCS
```

- [Mermaid source](12-dr-topology.mmd) · [SVG export](rendered/12-dr-topology.svg)

<a id="13-mysql-privilege-model"></a>
## 13-mysql-privilege-model — Mysql Privilege Model

```mermaid
%% 13 - Cloud SQL for MySQL 8.4: identities, accounts, roles and the isolation gate on a shared pool
%% Final reconciliation (M1-M8, G1-G5). Illustrative names. Nothing tested yet (see T-M*, T-G* tests).
flowchart LR
  subgraph IAMLAYER["IAM layer (project plt-sql-prd-01)"]
    direction TB
    GC["grp-wl-sqlconn-prd-01<br/>mechanism 1: project IAM policy only<br/>cloudsql.client + cloudsql.instanceUser<br/>= may ATTEMPT to log in (T-G2, mandatory)<br/>never added to the instance"]
    GD["grp-hum-dba-prd-ro / -admin (expiring membership, K21)<br/>mechanism 2: added to instance as<br/>IAM group DB user (humans only,<br/>max 3 of 200 groups per instance)"]
    BOOT["sqlboot-prd@plt-sql-prd-01<br/>individual IAM user"]
  end

  subgraph IDS["Workload identities (individual SAs)"]
    direction TB
    A_APP["abc-payroll-prd@t-abc-prd"]
    A_MIG["abc-payroll-prd-mig@t-abc-prd"]
    X_APP["xyz-payroll-prd@t-xyz-prd"]
  end

  subgraph INST["sql-prd-payroll-01 - Cloud SQL for MySQL 8.4 (HA, private IP, IAM auth on, mandatory_roles empty)"]
    direction TB
    subgraph ACC["MySQL accounts (username = SA local part, max 32 chars)"]
      U1["'abc-payroll-prd'@'%'<br/>default role r_abc_payroll_app"]
      U2["'abc-payroll-prd-mig'@'%'<br/>default role r_abc_payroll_ddl"]
      U3["'xyz-payroll-prd'@'%'<br/>default role r_xyz_payroll_app"]
      U4["'sqlboot-prd'@'%'<br/>cloudsqlsuperuser"]
      U5["group account for grp-hum-dba-prd-ro<br/>diagnostics read-only role"]
      ROOT["'root'@'%'<br/>sealed password, break-glass only"]
    end
    subgraph ROLES["Per-database roles (no *.* grants, no PROCESS, no GRANT OPTION)"]
      R1["r_abc_payroll_app<br/>SELECT INSERT UPDATE DELETE EXECUTE<br/>ON abc\_payroll.*"]
      R2["r_abc_payroll_ddl<br/>app privileges + CREATE ALTER DROP INDEX ...<br/>ON abc\_payroll.*"]
      R3["r_xyz_payroll_app<br/>ON xyz\_payroll.*"]
    end
    DB1[("abc_payroll")]
    DB2[("xyz_payroll")]
    CAN[("canary databases<br/>incl. wildcard trap")]
  end

  TEST["Isolation test ISO-01..10<br/>mandatory gate on onboarding,<br/>grant change, new pool, nightly sample"]

  A_APP -. "member" .-> GC
  A_MIG -. "member" .-> GC
  X_APP -. "member" .-> GC
  A_APP -- "Auth Proxy, automatic IAM auth" --> U1
  A_MIG -- "migration Job only" --> U2
  X_APP --> U3
  BOOT --> U4
  GD --> U5
  U1 --> R1 --> DB1
  U2 --> R2 --> DB1
  U3 --> R3 --> DB2
  U1 -. "DENIED (error 1142)" .-x DB2
  U3 -. "DENIED" .-x DB1
  U1 -. "DENIED" .-x CAN
  U4 -- "creates roles, grants,<br/>verifies SHOW GRANTS" --> ROLES
  U4 --> TEST

  classDef abc fill:#fff3cd,stroke:#b8860b,color:#000
  classDef xyz fill:#d4edda,stroke:#2e7d32,color:#000
  classDef plat fill:#eeeeee,stroke:#555,color:#000
  class A_APP,A_MIG,U1,U2,R1,R2,DB1 abc
  class X_APP,U3,R3,DB2 xyz
  class GC,GD,BOOT,U4,U5,ROOT,CAN,TEST plat
```

- [Mermaid source](13-mysql-privilege-model.mmd) · [SVG export](rendered/13-mysql-privilege-model.svg)
