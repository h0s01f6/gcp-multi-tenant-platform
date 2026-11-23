# Architecture diagrams

## Start with the five conceptual diagrams

These are the primary diagrams for the assignment. They are intentionally simplified to explain the design before showing implementation details. GitHub renders the Mermaid diagrams inline in the [Architecture Overview](../documentation/reviewer-guide.md).

| Diagram | What it explains | Open |
|---|---|---|
| 1. Overall platform | Users, entry layer, runtime choices, data and automation | [Architecture Overview — overall architecture](../documentation/reviewer-guide.md#2-overall-architecture) |
| 2. Customer and environment model | Customer projects, four environments and shared platform services | [Architecture Overview — customer and environment model](../documentation/reviewer-guide.md#3-customer-and-environment-model) |
| 3. GKE runtime | Cluster, namespaces, Helm, workload identity and data access | [Architecture Overview — GKE](../documentation/reviewer-guide.md#51-gke) |
| 4. Cloud Run runtime | Load balancing, customer service, identity and private data access | [Architecture Overview — Cloud Run](../documentation/reviewer-guide.md#52-cloud-run) |
| 5. MIG runtime | Packer, Ansible, images, instance templates and managed groups | [Architecture Overview — MIG](../documentation/reviewer-guide.md#53-compute-engine-managed-instance-groups-mig) |
| 6. Delivery flow | Change review, Terraform, deployment, verification and promotion | [Architecture Overview — automation](../documentation/reviewer-guide.md#8-how-infrastructure-and-releases-are-automated) |

## Detailed implementation diagrams

The following diagrams are retained as optional references for readers who want to inspect lower-level design details. They are not the recommended starting point.

| File | Subject |
|---|---|
| [01-resource-hierarchy.mmd](01-resource-hierarchy.mmd) | GCP organisation, folders and projects |
| [06-onboarding-workflow.mmd](06-onboarding-workflow.mmd) | Customer onboarding workflow |
| [07-lifecycle-operations.mmd](07-lifecycle-operations.mmd) | Subscription and lifecycle operations |
| [08-abc-xyz-example.mmd](08-abc-xyz-example.mmd) | Worked customer/product example |
| [09-prod-to-nonprod-data-flow.mmd](09-prod-to-nonprod-data-flow.mmd) | Controlled data movement |
| [10-identity-access.mmd](10-identity-access.mmd) | Identity and access model |
| [11-network-security.mmd](11-network-security.mmd) | Network boundaries and security controls |
| [12-dr-topology.mmd](12-dr-topology.mmd) | Disaster-recovery topology |
| [13-mysql-privilege-model.mmd](13-mysql-privilege-model.mmd) | MySQL database and privilege model |

The editable Mermaid source files are the source of truth. The simplified primary diagram sources are [02-platform-architecture.mmd](02-platform-architecture.mmd), [14-customer-environment-model.mmd](14-customer-environment-model.mmd), [03-gke-runtime.mmd](03-gke-runtime.mmd), [04-cloudrun-runtime.mmd](04-cloudrun-runtime.mmd), [05-mig-runtime.mmd](05-mig-runtime.mmd) and [15-delivery-flow.mmd](15-delivery-flow.mmd). Older detailed SVG exports are retained only for the optional implementation diagrams; the primary diagrams are rendered inline by GitHub from the Mermaid blocks in the Architecture Overview.
