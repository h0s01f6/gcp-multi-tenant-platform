# Multi-Tenant GCP Platform – DevOps Architect Assignment

Architecture and reference implementation for a GCP platform hosting 15–20 products for 200+ customers across Dev, Stage, UAT and Prod, using GKE, Cloud Run and Compute Engine Managed Instance Groups.

## Start here

**Read the [Architecture Overview](documentation/reviewer-guide.md) first.** It explains the tenancy model, deployment choices, runtime diagrams, version handling, data isolation and automation without requiring you to navigate the implementation details.

## Assignment deliverables

| Requested deliverable | Repository location |
|---|---|
| Overall GCP infrastructure architecture | [Architecture Overview](documentation/reviewer-guide.md) and [detailed architecture](architecture/stage-2-platform-architecture.md) |
| GKE runtime diagram | [Diagram 03](diagrams/rendered/03-gke-runtime.svg) |
| Cloud Run runtime diagram | [Diagram 04](diagrams/rendered/04-cloudrun-runtime.svg) |
| Instance Group runtime diagram | [Diagram 05](diagrams/rendered/05-mig-runtime.svg) |
| Terraform infrastructure automation | [`terraform/`](terraform/) |
| Helm charts for GKE | [`helm/`](helm/) |
| Documentation and examples | [`documentation/`](documentation/), [`registry/`](registry/), [`examples/`](examples/) |
| AI prompts log | [Prompts log](documentation/prompts-log.md) |

## Implementation at a glance

- **Tenancy:** customer production and non-production projects, with shared platform projects.
- **Deployment choices:** Dedicated by default; Shared and Cohort where application-level tenant isolation is appropriate.
- **GKE:** shared regional clusters, customer/product/environment namespaces and Helm releases.
- **Cloud Run and MIG:** customer-scoped services and identities for Dedicated deployments.
- **Automation:** Terraform for infrastructure, Helm for GKE applications, Ansible for MIG configuration, and CI/CD workflows for validation and promotion.

## Validation status

The repository includes local validation tools and automated tests. The implementation **has not been deployed to or tested in GCP**, and the application deployment workflows have not been run against live infrastructure. The repository's own CI workflow is separate from those deployment workflows.

Previously reported local results are 26 `check_all` steps with zero findings and 386 passing pytest tests. Re-run them in your environment using:

```bash
python3 -m tools.check_all
python3 -m pytest -q
```

Terraform init/validate/plan/apply, real Cloud SQL isolation, live workflow execution, and runtime deployment and rollback still require a GCP test environment.

## Supporting technical references

These are available for deeper review, but are not required as a first read:

- [Terraform and Helm implementation](documentation/stage-5-6-terraform-helm.md)
- [CI/CD, cost, SLO and DR](documentation/stage-7-8-cicd-cost-slo.md)
- [Security implementation](documentation/stage-3-security-implementation.md)
- [Networking implementation](documentation/stage-4-networking.md)
- [Database architecture](documentation/database-architecture-mysql.md)
- [Identity and groups](documentation/identity-and-groups-model.md)
- [Assumptions and open questions](documentation/assumptions-and-open-questions.md)
- [Requirements traceability](documentation/requirements-traceability.md)
- [Architecture decision records](architecture/decisions/)
- [Prompts log](documentation/prompts-log.md)

The remaining diagrams in [`diagrams/`](diagrams/) and detailed design documents are supporting material for specific implementation questions.
