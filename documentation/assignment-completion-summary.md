# Assignment completion summary (Stages 1–8)

**Status as of 2026-11-23.**
- Every assignment section is designed, implemented as configuration and code, and checked locally.
- **Nothing has been deployed to or tested in Google Cloud**, and no GitHub workflow has run except this repository's own CI (`.github/workflows/ci.yml`, which needs no cloud access).
- Cost figures are indicative planning estimates, not quotes.

**Local verification:**
- `python3 -m tools.check_all`: 26 generators and checkers, 0 findings.
- `python3 -m pytest -q`: 386 tests passing.

## 1. Deliverables by stage

| Stage | Deliverables | Implemented | Locally tested |
|---|---|---|---|
| 1 / 1b | Requirements register, three isolation approaches compared, recommendation (hybrid project model) | ✅ docs | – |
| 2 | Architecture (folders, projects, runtimes, data, identity, network, ops), ADR-001…011, diagrams 01–13, capacity model, review | ✅ docs + `scripts/capacity_model.py` | name / capacity scripts |
| 3 | Security: registry (D1), identity plan (D2), access matrix (D3), MySQL isolation gate (D4), org policies (D5), CI/CD identities (D6), privileged access (D7), Kubernetes baseline (D8), data protection (D9), audit + alerts (D10), consolidation (D11) | ✅ | ✅ D1–D10 checkers + tests |
| 4 | Networking: IP plan, VPC / Shared VPC, firewall, DNS / ingress / egress / NAT, quotas (N1–N5) | ✅ | ✅ |
| 5 | Terraform: 18 modules, 10 stacks, stack catalogue, tfvars bridge | ✅ | ✅ static checks (HC01–HC07, SK01–SK05); no `terraform` binary |
| 6 | Helm library + payroll chart, Terraform → Helm contract, Ansible for MIG | ✅ | ✅ offline render of 8 releases |
| 7 | CI/CD: planner (PL01–PL05), 13 reusable + 12 caller workflows in 8 repositories, generated pipelines, onboarding, promotion, rollback, drift, failure handling, self-service evaluation | ✅ | ✅ PL / CW rules, 39 tests |
| 8 | Cost (200 / 500 customers, 1–20 products), capacity triggers, SLOs + monitoring, backup, DR with RPO / RTO, implementation phases | ✅ | ✅ CO / CP / SL / BC rules, 23 tests |

Detail per stage is in the following documents:
- [`stage-3-security-implementation.md`](stage-3-security-implementation.md)
- [`stage-4-networking.md`](stage-4-networking.md)
- [`stage-5-6-terraform-helm.md`](stage-5-6-terraform-helm.md)
- [`stage-7-8-cicd-cost-slo.md`](stage-7-8-cicd-cost-slo.md)

Coverage per assignment section is in [`requirements-traceability.md`](requirements-traceability.md).

## 2. Headline results

| Topic | Result |
|---|---|
| Isolation | Project per customer per tier; database per customer-product with an isolation gate (ISO-01..10, 847 generated cases) before any release |
| Prod access | No standing human write; PAM / expiring groups / break-glass (D7); prd changes only by reviewed pipelines in central reusable workflows |
| Cost (Baseline, 3 products) | 200 customers: $131k list, $85k optimised per month. 500 customers: $302k list, $197k optimised per month (≈ $394–$654 per customer) |
| Availability | 99.9 % per customer per product in prd, measured from load-balancer SLIs with multi-window burn-rate alerts |
| DR | Zone: RPO 0 / RTO 5 min (automated). Corruption: RPO 5 min / RTO 4 h. Region: RPO 15 min / RTO 4 h once regional DR is activated (Q10); interim RPO 24 h / RTO 48 h |

## 3. Outstanding GCP / GitHub validation (in recommended order)

These items are listed in [`assumptions-and-open-questions.md`](assumptions-and-open-questions.md), and the phases are in [`stage-7-8-cicd-cost-slo.md`](stage-7-8-cicd-cost-slo.md) §4.

1. **Foundations.** Org policies in dry-run (T-O*), WIF and GitHub environments (T-W*, T-CI2, T-CI3), audit sharing (T-A1).
2. **Terraform.** First `init` / `validate` / `plan` / `apply` of every stack (T-TF1–T-TF6) in a test organisation.
3. **Network.** Connectivity, firewall and egress tests (T-N*).
4. **Data isolation.** MySQL mapping and the isolation gate on real Cloud SQL (T-M*, D4).
5. **Charts and Ansible.** Real Helm, Policy Controller and Binary Authorization admission (T-H1–T-H4); Ansible / Packer (T-AN1).
6. **Pipelines.** Build gates and signing (T-CI5), release and rollback mechanics (T-CI4), drift exports (T-CI6, T-A4), action pinning (T-CI1).
7. **Monitoring.** SLOs, log-based SLIs, alerts, uptime checks and scopes (T-SL1–T-SL6).
8. **Backup and DR.** Zone drill, PITR timing, backup location, pre-release backup (T-DR1–T-DR3, T-DR5); regional replica after Q10 (T-DR4).
9. **Cost.** asia-south1 prices and discounts, measured usage, billing export (T-CO1, T-CO2).

## 4. Remaining assumptions and open decisions

| Topic | Items |
|---|---|
| Business decisions | Q10 regional DR scope; Q11 retention; Q22 product sizing; Q25 paging integration; B1 / B10 review items |
| Key assumptions | A8 targets (now design values); A-S8-2 price factor; A-S8-3 illustrative sizing; A-S8-4 restore throughput; A-S7-2 MIG migrations; A-H-1 product contract |
| Accepted risks | R-S7-1 cross-repository state lock; R-S7-2 backup as `tf-prd`; R-S8-1 MIG floor cost; R-S8-2 restore time near the RTO; R-S8-3 DR not activated; plus earlier R-D*/R-N*/R-TF* items |
