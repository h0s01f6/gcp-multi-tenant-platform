# GCP Multi-Tenant Platform – Architecture Assignment

Design for a multi-tenant Google Cloud platform hosting 15–20 products for 200+ customers across Dev, Stage, UAT and Prod, on GKE, Cloud Run and Compute Engine MIGs.

> **Status:** All stages (1–8) complete at configuration and code level, with local checks (`check_all`: 26 steps, 0 findings; `pytest`: 386 passing). **Nothing has been deployed or tested in GCP**, and no pipeline has run except this repository's own CI. Start with [`documentation/assignment-completion-summary.md`](documentation/assignment-completion-summary.md). Outstanding validation items are in [`documentation/assumptions-and-open-questions.md`](documentation/assumptions-and-open-questions.md).

## Contents

| Path | What it contains |
|---|---|
| [`architecture/stage-2-platform-architecture.md`](architecture/stage-2-platform-architecture.md) | Main architecture document with all diagrams rendered inline |
| [`documentation/assignment-completion-summary.md`](documentation/assignment-completion-summary.md) | **Final summary:** deliverables per stage, headline results, ordered GCP validation, open decisions |
| [`documentation/stage-7-8-cicd-cost-slo.md`](documentation/stage-7-8-cicd-cost-slo.md) | **Stages 7–8 consolidated:** pipelines, promotion, onboarding, failure handling, cost, capacity, SLOs, monitoring, backup, DR, implementation phases |
| [`documentation/cost-estimate.md`](documentation/cost-estimate.md) | Generated cost estimate for 200 / 500 customers × 1–20 products |
| [`documentation/stage-5-6-terraform-helm.md`](documentation/stage-5-6-terraform-helm.md) | **Stages 5–6 consolidated:** responsibilities, stack order, Terraform → Helm interface, coverage, validation |
| [`documentation/stage-4-networking.md`](documentation/stage-4-networking.md) | **Stage 4 consolidated:** network isolation, address plan, runtime connectivity, firewall layering, DNS, carried-forward items |
| [`documentation/stage-3-security-implementation.md`](documentation/stage-3-security-implementation.md) | **Stage 3 consolidated:** deliverables D1–D11, status, alerts, corrections, carried-forward items, validation order |
| [`architecture/decisions/`](architecture/decisions/) | Architecture Decision Records ADR-001 … ADR-011 |
| [`documentation/database-architecture-mysql.md`](documentation/database-architecture-mysql.md) | Cloud SQL for MySQL 8.4: isolation, accounts, roles, bootstrap, isolation tests, migrations, pooling |
| [`documentation/identity-and-groups-model.md`](documentation/identity-and-groups-model.md) | Human, pipeline and workload identities; hybrid Cloud Identity groups model |
| [`documentation/stage-2-architecture-review.md`](documentation/stage-2-architecture-review.md) | Stage 2 review: feasibility, security paths, consistency, completeness, findings A–E |
| [`documentation/capacity-model.md`](documentation/capacity-model.md) | Capacity across 200/500 customers × 1–20 products per customer |
| [`CHANGELOG.md`](CHANGELOG.md) | Traceable list of changes by review ID |
| [`diagrams/`](diagrams/) | Mermaid sources (`*.mmd`) – the single source of truth for every diagram; `rendered/` holds SVG exports |
| [`documentation/assumptions-and-open-questions.md`](documentation/assumptions-and-open-questions.md) | Confirmed requirements, assumptions, recommendations, open questions |
| [`documentation/requirements-traceability.md`](documentation/requirements-traceability.md) | Assignment section → where it is addressed |
| [`scripts/embed_diagrams.py`](scripts/embed_diagrams.py) | Inlines `.mmd` files into `*.src.md` docs to keep docs and diagrams in sync |
| [`registry/naming-rules.md`](registry/naming-rules.md) | Tenant registry schema v2.1 naming rules (service-account length budget) |
| [`scripts/validate_names.py`](scripts/validate_names.py) | Naming validator with boundary tests |
| [`scripts/capacity_model.py`](scripts/capacity_model.py) | Planning calculator that generates the capacity-model tables (illustrative inputs) |
| [`registry/`](registry/) | Stage 3 D1 – tenant registry schemas, inventory, example products and tenants |
| [`tools/`](tools/) | Stage 3 generators and checkers: registry (D1), identity plan (D2), access matrix (D3), MySQL grants + isolation harness (D4), org policies (D5), CI/CD federation (D6), privileged access (D7), namespace baseline (D8), data protection (D9), audit and alerts (D10), `check_all` (D11) |
| [`security/`](security/) | Stage 3 access matrix (D3), organisation policies (D5), CI/CD identities (D6), privileged access (D7), Kubernetes baseline inputs (D8), secrets/keys/supply chain (D9), audit logging and alerts (D10) |
| [`network/`](network/) | Stage 4 networking: IP plan, VPC / Shared VPC, firewall, DNS / ingress / egress, quota register (N1–N5) |
| [`terraform/`](terraform/) | Stage 5: 18 modules, 10 stacks (Stage 8 adds `observability`), stack catalogue |
| [`cicd/`](cicd/) | Stage 7: reusable workflows (`platform-workflows`) and caller workflows per repository |
| [`cost/`](cost/), [`slo/`](slo/) | Stage 8: cost-model inputs and capacity thresholds; SLOs, alerts, backup and DR targets |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | CI of this repository (runs `check_all` + tests; no cloud access) |
| [`helm/`](helm/) | Stage 6: library chart, payroll chart, environment values |
| [`ansible/`](ansible/) | Stage 6: MIG image bake and day-2 configuration |
| [`interfaces/`](interfaces/) | Terraform -> Helm values contract |
| [`examples/`](examples/) | Generated ABC/XYZ Terraform inputs and Helm values/manifests |
| [`policies/k8s/`](policies/k8s/) | Stage 3 D8 – Gatekeeper / Policy Controller templates (Rego) |
| [`tests/`](tests/) | Automated local tests (`python3 -m pytest -q tests`) |

## Diagram index

| # | Diagram |
|---|---|
| 01 | Resource hierarchy (org, folders, projects) |
| 02 | Overall platform architecture |
| 03 | GKE runtime (Payroll) |
| 04 | Cloud Run runtime (CRM) |
| 05 | Compute Engine MIG runtime (illustrative "Ledger") |
| 06 | New customer onboarding workflow |
| 07 | Day-2 lifecycle: add product, upgrade, offboard |
| 08 | ABC / XYZ worked example (all four environments) |
| 09 | Controlled Prod → non-prod data movement |
| 10 | Identity and access |
| 11 | Network isolation and traffic controls |
| 12 | High availability and disaster recovery |
| 13 | Cloud SQL for MySQL identities, accounts, roles and isolation gate |

## Regenerating

```bash
python3 -m tools.check_all                            # every generator/checker of Stages 3–8 (26 steps)
python3 -m pytest -q tests                            # all local tests (386)
```

```bash
python3 scripts/embed_diagrams.py                     # refresh docs from diagram sources
npx -p @mermaid-js/mermaid-cli mmdc -i diagrams/03-gke-runtime.mmd -o diagrams/rendered/03-gke-runtime.svg
```
