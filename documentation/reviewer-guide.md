# Multi-Tenant GCP Platform – Architecture Overview

## 1. Problem and design goals

The platform hosts 15–20 products for 200+ customers across Dev, Stage, UAT and Prod. Products may run on GKE, Cloud Run or Compute Engine Managed Instance Groups (MIGs). Customers may subscribe to multiple products, run different product versions and apply customer-specific configuration.

The design aims to:

- isolate customer workloads and data;
- support all four environments and controlled data movement between a customer's own environments;
- allow product versions to differ by customer where the deployment model supports it;
- reuse platform services and automation without giving customers direct GCP administration access;
- scale by adding customers and capacity cells rather than redesigning the platform.

## 2. Tenancy and environment model

The recommended model is hybrid:

- Each customer has a **non-production project** for Dev, Stage and UAT, and a separate **production project**.
- Shared platform projects provide centrally managed services such as networking, GKE clusters, ingress, build artifacts and observability.
- GKE workloads use customer/product/environment namespaces on shared regional clusters. Cloud Run services and MIGs run in the appropriate customer project for Dedicated deployments.
- Customer data and workload identities remain customer-scoped for Dedicated deployments. Shared services are granted only the access they need.

This avoids creating a separate GCP project for every product/environment combination while retaining a meaningful production boundary for each customer.

## 3. Product deployment models

The product catalogue declares one of three deployment models:

| Model | Deployment pattern | Version handling | Isolation boundary |
|---|---|---|---|
| Dedicated (default) | Separate customer deployment | Each customer can run its own version | Platform / infrastructure boundary |
| Shared | One product deployment serves multiple customers | One common version; customer differences use configuration or feature flags | Application logic |
| Cohort | One deployment per version cohort | Customers in different cohorts can run different versions | Application logic within each cohort |

Dedicated is the default because it provides the clearest isolation. Shared and Cohort are options only where the product is designed and reviewed for application-level tenant isolation. This trade-off is explicit: a shared product identity can access the customer databases assigned to that shared deployment, so application code must enforce tenant separation.

## 4. Runtime architectures

The assignment asks for one architecture diagram per runtime. These are the three primary runtime diagrams:

### GKE

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

GKE provides shared regional clusters with separate namespaces and Helm releases. Customer-specific service accounts, secrets, storage and database grants are used for Dedicated workloads. Network policies and namespace controls limit workload communication.

### Cloud Run

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

Cloud Run services are deployed per customer for Dedicated products. A shared external load balancer routes customer hostnames to the correct service. Services use customer-scoped identities and private connectivity to required data services.

### Compute Engine MIG

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

MIG products use versioned machine images built with Packer and Ansible. Regional managed instance groups provide rolling updates, health checks and autoscaling. Instances use customer-scoped service accounts and private access to data services.

## 5. Version divergence and customer customisation

A tenant/product subscription is represented in the registry. For Dedicated deployments, the subscription records the version and configuration for each environment. The same product can therefore run version 2.x for one customer and 1.x for another. Shared deployments use a common product version with customer-specific configuration; Cohort deployments assign customers to a version cohort.

Changes are promoted through Dev → Stage → UAT → Prod. Environment-specific configuration is kept separate from the product image or chart, and deployed artifacts are versioned and immutable.

## 6. Data isolation and controlled sharing

For Dedicated deployments, each customer has a separate database/schema boundary, workload identity and scoped grants. Shared or Cohort products retain a database per customer but use a shared product identity for the databases served by that deployment; tenant isolation is therefore enforced by the product application and must be tested by the product team.

Data movement is controlled and limited to the same customer's environments. Production data is not copied directly into lower environments as-is; the designed flow uses an approved, masked or sanitised dataset. There is no cross-customer data sharing in the design.

## 7. Infrastructure and application automation

- **Terraform** provisions GCP foundations and runtime infrastructure, including projects, networking, platform services and tenant resources.
- **Helm** packages and deploys GKE applications. It consumes the release configuration produced from the tenant/product registry; it does not own shared cluster foundations.
- **CI/CD workflows** validate changes, plan and apply infrastructure, build and scan artifacts, promote releases, and run deployment checks. GitHub Actions is used for the reference workflow implementation; the design can be adapted to Bitbucket.
- **Ansible** supports configuration and day-2 operations for MIG-based products. Shared runners are centrally managed and use scoped identities.

## 8. Repository validation and limitations

The repository includes Terraform modules and stacks, Helm charts, Ansible playbooks, registry examples, workflow definitions, diagrams, documentation and local automated checks.

The implementation has been checked locally. **It has not been deployed to or tested in a GCP organisation.** Terraform plans/applies, real Cloud SQL isolation tests, live GitHub/Bitbucket workflow execution, and runtime deployment/rollback tests remain validation steps. Cost figures and service-level targets are design assumptions for assessment purposes, not confirmed commercial commitments.

## 9. Further technical references

The following documents provide implementation detail if required; they are supporting references rather than prerequisites for understanding the design:

- [Terraform and Helm implementation](stage-5-6-terraform-helm.md)
- [CI/CD, cost, SLO and DR details](stage-7-8-cicd-cost-slo.md)
- [Security implementation](stage-3-security-implementation.md)
- [Networking implementation](stage-4-networking.md)
- [Assumptions and open questions](assumptions-and-open-questions.md)
- [Requirements traceability](requirements-traceability.md)
- [Prompts log](prompts-log.md)
