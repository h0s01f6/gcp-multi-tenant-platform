# Multi-Tenant GCP Platform

Architecture and reference implementation for hosting **15–20 products across 200+ customers** on GCP, across Dev, Stage, UAT and Prod.

## Start here

**[Read the Architecture Overview](documentation/reviewer-guide.md)** — the recommended starting point. It explains the tenancy model, environment layout, three runtimes, version divergence, data isolation and automation using simple diagrams.

## Assignment deliverables

| Requested deliverable | Repository location |
|---|---|
| GCP infrastructure architecture | [Architecture Overview](documentation/reviewer-guide.md) and [platform architecture](architecture/stage-2-platform-architecture.md) |
| GKE architecture | [Runtime diagrams](diagrams/README.md#3-gke-runtime) |
| Cloud Run architecture | [Runtime diagrams](diagrams/README.md#4-cloud-run-runtime) |
| Compute Engine MIG architecture | [Runtime diagrams](diagrams/README.md#5-compute-engine-mig-runtime) |
| Terraform infrastructure automation | [`terraform/`](terraform/README.md) |
| Helm charts for GKE | [`helm/`](helm/README.md) |
| Documentation and AI prompts | [`documentation/`](documentation/) and [prompts log](PROMPTS.md) |

## Key design decisions

- **Hybrid tenancy:** a production and a non-production project per customer, with shared platform projects for common services.
- **Four environments:** Dev, Stage and UAT in the non-production tier; Prod in a separate production tier.
- **Three runtimes:** shared regional GKE clusters, customer-scoped Cloud Run services and customer-scoped regional MIGs for Dedicated deployments.
- **Deployment models:** Dedicated by default; Shared and Cohort only where application-level tenant isolation is appropriate.
- **Version divergence:** per-customer versions for Dedicated deployments and per-cohort versions for Cohort deployments.
- **Data isolation:** customer-scoped workload identities and database permissions; controlled, masked data movement to non-production.
- **Automation:** Terraform for infrastructure, Helm for GKE releases, and shared CI/CD / Ansible delivery services.

## Repository map

| Directory | Contents |
|---|---|
| `documentation/` | Reviewer guide, assignment traceability, stage implementation notes and assumptions |
| `architecture/` | Detailed platform architecture and design decisions |
| `diagrams/` | Primary diagrams plus optional detailed implementation diagrams |
| `terraform/` | Terraform modules, stacks and environment configuration |
| `helm/` | Shared chart library and product charts |
| `ansible/` | Packer and Ansible image/configuration automation |
| `registry/` | Tenant and product registry examples, schemas and naming rules |
| `security/`, `network/`, `slo/`, `cost/` | Supporting platform configuration |
| `tests/`, `tools/` | Local validation and consistency checks |
| `PROMPTS.md` | AI prompts and engineering decision log (start here for the AI-use record) |

## Validation status

The project includes local validation and test tooling. The completion summary records the reported local test results. **No GCP deployment, GCP integration test or real CI/CD deployment workflow has been run.** Treat cost figures, capacity thresholds, SLOs and DR timings as design assumptions pending validation against the target GCP organisation and business requirements.

## Useful links

- [Architecture Overview](documentation/reviewer-guide.md)
- [Diagrams index](diagrams/README.md)
- [Assignment completion summary](documentation/assignment-completion-summary.md)
- [Requirements traceability](documentation/requirements-traceability.md)
- [Prompts log](PROMPTS.md)
- [Assumptions and open questions](documentation/assumptions-and-open-questions.md)
