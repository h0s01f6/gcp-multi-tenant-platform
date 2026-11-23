# AI prompts and engineering decision log

**Project:** Multi-tenant GCP platform for Impact Analytics  
**Role of AI:** Implementation and review assistant  
**Status:** Prepared for assignment handover, 23 November 2026

## Purpose and scope of this prompt log

This document provides a consolidated record of the main instructions, architectural directions and review prompts used during the development of this assignment with Claude.

It is organised by assignment stage to make the progression of the work and the reasoning behind key implementation decisions clear.

Where the original prompt wording was available, it has been retained. Where the original wording was not available, the entry is presented as a summary of the instruction and intent rather than as a verbatim prompt. This document is not intended to be a complete transcript of every interaction.

The purpose is to demonstrate how the assignment was approached: understanding the requirements, establishing the architecture, translating design decisions into implementation, reviewing trade-offs, challenging inconsistencies and validating the resulting work.

The assignment requirements and documented architecture decisions remain the source of truth. Claude was used as an implementation and review assistant, with the architectural direction and acceptance criteria defined through the project instructions.

## Working principles used across stages

The recurring direction to Claude was:

- Treat the assignment brief as the scope boundary. Do not add services, features or operational complexity unless a stated requirement needs them.
- Work incrementally against the existing repository and architecture. Inspect what is already present before implementing; avoid recreating completed work.
- Keep customer, product and environment boundaries explicit. Preserve the agreed identity, data-isolation, network and deployment models.
- Prefer declarative, repeatable implementation: Terraform for cloud infrastructure, Helm for Kubernetes application releases, and Ansible/Packer for the VM-based runtime path.
- Keep generated configuration and implementation consistent with the registry, access matrix, naming rules, stack catalogue and documented architecture decisions.
- Add tests and traceability for meaningful behaviour. Include negative tests for security and isolation controls, not only happy paths.
- Distinguish design, implementation, local validation and real GCP validation. Never report a deployment, cloud integration test or workflow run unless it actually happened.
- Record assumptions, unresolved business decisions, risks and external validation steps rather than inventing answers.

## Stage 1 – Understand the assignment and establish the architecture

**Architectural direction (reconstructed from the initial project discussion)**

> Review the assignment requirements and turn them into a clear set of architectural requirements and constraints. Compare viable multi-tenant deployment and isolation approaches, explain their trade-offs, and recommend an approach that can support the stated customer and product scale. Keep the design grounded in the assignment rather than assuming requirements that have not been provided. Record assumptions and questions that need confirmation.

**Follow-up direction (reconstructed)**

> Make the recommendation explicit and defensible. Address the project and environment model, customer isolation, product subscription differences, runtime choices, data handling, disaster recovery and operational ownership. Show why the selected approach is preferable to the alternatives and retain the alternatives in the design record.

**Intent:** Establish the problem and decision criteria before generating implementation. The architecture compared stronger per-customer separation with shared-project efficiency and selected a hybrid model with explicit isolation boundaries.

## Stage 2 – Convert the architecture into a technical design

**Technical-design prompt (reconstructed)**

> Expand the approved architecture into an implementable GCP design. Define the project and folder structure, environment separation, GKE/Cloud Run/MIG placement, database and storage model, workload identities, networking, ingress/egress, deployment tiers and operating model. Show how the design supports customer subscriptions to different products and versions. Include capacity assumptions for 200 and 500 customers, identify scaling constraints, and record decisions and open questions. Keep the design consistent with the assignment scope.

**Review and refinement direction (reconstructed)**

> Review the design for consistency and operational feasibility. Make the isolation guarantees precise for Dedicated, Shared and Cohort products; distinguish infrastructure permissions from database permissions; validate naming limits and identity derivation; and ensure non-production data is handled through an explicitly controlled, masked flow. Update the architecture decisions and tests where a correction is needed.

**Intent:** Move from a conceptual architecture to a design that can drive registry, identity, security, networking and infrastructure code. Important trade-offs were documented rather than hidden, including application-level isolation for Shared/Cohort deployments.

## Stage 3 – Implement security, identity and governance controls

**Stage objective prompt (reconstructed)**

> Implement the security design in small, independently verifiable parts. Start with the tenant/product registry and validation rules, then derive workload identities and access groups, build the access matrix and database grants, and implement organisation policies, CI/CD identities, privileged access, Kubernetes security, secrets/key protection and audit controls. Use the existing architecture and naming conventions. Add deterministic generators, validation tools and tests so the controls can be checked locally.

**Security review prompts (reconstructed)**

> Check that workload identities receive only the permissions required for their runtime and customer/product scope. Do not let shared workload groups accidentally grant customer-specific database access. Verify the Shared/Cohort isolation model against the documented ADR, and make the application-level boundary explicit. Check that production human access is time-bound and approved, that break-glass access is separately controlled, and that CI identities are restricted to the intended repository, environment and branch.

> Review the generated database grants for least privilege. Confirm there are no unintended global privileges, grant options or administrative privileges. Add isolation tests that demonstrate both allowed access and denied cross-customer/cross-environment access under the chosen deployment model.

> Validate the Kubernetes baseline, organisation policies, secret/key configuration and audit rules against the security design. Where a tool or real cloud environment is unavailable, report the limitation and do not imply that the policy has been enforced in GCP.

**Intent:** Treat security as a set of enforceable controls with traceable inputs and local tests, rather than as a narrative-only section. The review directions also forced the design to state where isolation is infrastructure-enforced and where it relies on application-level enforcement.

## Stage 4 – Design and validate the network foundation

**Networking prompt (reconstructed)**

> Implement the network design from the approved architecture: private address allocation, Shared VPCs, tier separation, GKE and workload subnets, Cloud SQL private connectivity, firewall policy, DNS, ingress/egress, NAT and quota assumptions. Keep production and non-production boundaries clear. Make the configuration consistent with the project model and identity permissions, and add local checks for address overlap, required ranges, policy coverage and references.

**Review direction (reconstructed)**

> Check that the network controls match the actual runtime paths. Avoid broad project-wide network permissions where subnet-level permissions are sufficient. Confirm that private workloads do not gain unintended public access, and document product-specific egress requirements as assumptions where the assignment does not provide them.

**Intent:** Ensure network security was designed alongside workload placement and IAM, rather than added as a generic network diagram.

## Stage 5 – Build the Terraform infrastructure layer

**Terraform implementation prompt (reconstructed)**

> Implement reusable Terraform modules and independently managed stacks for the approved GCP architecture. Cover organisation/folder/project foundations, networking, platform services, security, shared infrastructure and tenant/product resources. Keep state boundaries and apply dependencies explicit. Generate example configuration from the registry and existing design inputs. Ensure Terraform owns cloud infrastructure and platform-owned Kubernetes foundations, not application release resources that belong in Helm.

**Review direction (reconstructed)**

> Check module inputs/outputs, naming, stack dependencies, state layout, least-privilege deployment identities and consistency with the access matrix. Add static validation and tests. Clearly identify anything that requires Terraform CLI, provider access or a real GCP organisation and therefore cannot be validated in the current environment.

**Intent:** Make infrastructure reproducible and modular while preserving the boundary between platform provisioning and application deployment.

## Stage 6 – Build the application delivery layer

**Helm and Ansible prompt (reconstructed)**

> Implement the agreed Helm library and application chart using the Terraform-to-Helm contract. Include the application release resources required by the design and support the relevant environment sizing. Keep platform-owned resources such as namespaces, service accounts, network policies, RBAC, quotas and shared gateways outside the application chart. For MIG-based products, provide the Packer/Ansible image-bake and day-two configuration path described by the architecture.

**Review direction (reconstructed)**

> Render representative releases and validate the chart contract against Terraform outputs. Check that Helm does not recreate resources owned by Terraform and that the GKE, Cloud Run and MIG deployment models remain consistent. Report unavailable Helm/Packer/Ansible tooling as a validation limitation rather than claiming a real deployment.

**Intent:** Keep ownership boundaries clear and ensure that the three supported runtime types have a defined delivery path.

## Stages 7 and 8 – Complete CI/CD, cost, SLOs and disaster recovery together

**Exact prompt retained from the Claude conversation**

> Stages 5 and 6 are accepted. Let's complete the remaining assignment by working on Stage 7 (CI/CD) and Stage 8 (Cost and SLOs) together.  
> Please use the existing architecture, Terraform modules, Helm charts, registry, identities and security controls.  
> Cover original assignment requirements for:
> - CI/CD workflows, infrastructure provisioning, application builds, security checks, deployment and customer onboarding.
> - Cost estimates for 200 and 500 customers, capacity planning and scaling.
> - Availability targets, monitoring objectives, RPO/RTO, backups and disaster recovery.  
> Keep implementation focused strictly on original assignment. Do not introduce additional products, features or infrastructure components unnecessarily.  
> Develop Stage 7 and Stage 8 in coordinated steps, dependencies clear. Run local tests and distinguish implemented, locally tested and GCP-tested.  
> Before starting, briefly show implementation plan and deliverables. Then proceed.  
> At end provide final assignment-completion summary, outstanding validation items and assumptions.

**Follow-up direction (reconstructed from the completion review)**

> Inspect the existing planner, workflows, workflow checks, cost model and capacity checks before changing anything. Complete only the remaining SLO, monitoring, backup and DR implementation, documentation/register updates and tests. Keep the implementation aligned with the existing Stage 3 identities and security controls, Stage 5 Terraform stacks and Stage 6 release mechanisms. Check workflow permissions, promotion order, approval gates, rollback paths, customer onboarding and capacity enforcement. Do not repeat completed work or expand the scope.

> Review the cost and capacity assumptions against the existing capacity model. Show the 200- and 500-customer scenarios and distinguish indicative list-price estimates from commitment/off-hours scenarios. Make the assumptions visible and avoid presenting estimates as billing quotes. Define availability objectives and monitoring in a way that can be measured, and document backup/restore and regional DR targets, dependencies and limitations.

> Run the repository checks and tests, update the traceability and assumptions registers, and produce a final assignment-completion summary. Explicitly state that no GCP deployment or cloud validation has taken place unless it has actually been performed.

**Intent:** Finish the delivery and operational model as one connected stage. CI/CD must consume the existing identity and infrastructure model; capacity controls must constrain onboarding; and SLO, backup and DR objectives must be tied to monitoring and recovery procedures.

## Final review and handover direction

**Final verification prompt (reconstructed)**

> Review the complete repository against the original assignment requirements. Check that the implementation, documentation, diagrams, examples, traceability matrix and tests agree. Identify missing deliverables, contradictory assumptions, accidental scope additions and claims that overstate validation. Run all available local checks and tests. Produce a concise handover summary with completed work, test evidence, open decisions, risks and the GCP validation sequence. Do not make further architectural changes unless a concrete defect or requirement gap is found.

**Handover principle:** The repository is presented as implemented and locally validated. It is not presented as deployed or tested in GCP. Indicative costs and unresolved business decisions remain clearly labelled.

## Evidence and limits

The repository contains the implementation, tests, architecture decision records, assumptions/open-questions register, requirements traceability and stage completion documents. The final completion summary reports 26 local check steps with zero findings and 386 passing tests. Those are the results recorded by the project run; this prompt log does not independently certify every command or any cloud deployment.

No real GCP deployment, Terraform apply, Cloud SQL isolation run, GitHub Actions deployment workflow, production release, backup restore drill or regional failover test is claimed here. The only pipeline run reported in the completion summary is the repository's own CI workflow, which does not require cloud access.

The exact Stage 7–8 combined prompt above is reproduced from the conversation. Other stage entries are labelled reconstructed because a complete verbatim export of all Claude messages was not available when this log was prepared.
