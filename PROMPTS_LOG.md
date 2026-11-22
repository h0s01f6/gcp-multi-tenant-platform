# Prompts Log

The assignment allows AI tools for the design, diagrams, Terraform and Helm work. This file records the prompts used and the tool each ran in.

| # | Date (IST) | Tool | Purpose |
|---|---|---|---|
| 1 | 2026-11-22 12:32 | Claude (claude.ai, model Claude Opus 5.5) | Understand the assignment |
| 2 | 2026-11-22 12:42 | Claude (claude.ai, model Claude Opus 5.5, agent mode with file and code-execution tools) | Generate design, diagrams, Terraform, Helm, CI and docs |
| … | | | *(append further prompts below as they are used)* |

---

## Prompt 1: Claude (claude.ai)

```text
DevOps Architect – Technical Assignment
[assignment email from the recruiter, followed by the full assignment text:]

DevOps Architect Assignment: Multi-Tenant GCP Platform
Design a multi-tenant, multi-product GCP infrastructure for four environments, then
prove it with architecture diagrams, Terraform and Helm charts pushed to a public
repository.

1. Scenario
A software company runs 15 to 20 products on Google Cloud and serves 200+ customers.
Design the infrastructure and automation that hosts all of them.
Environments: four per customer: dev, stage, uat and prod.
Products: 15 to 20 different products.
Runtimes: products are deployed on GKE, Cloud Run or Instance Groups.
Customers: 200+ customers.
Multi-product tenancy: one customer can run several products inside the same
infrastructure/project.
Version divergence: different customers can run the same product at different
versions, with customer-specific customizations.
Data sharing: a customer's data can be shared between that customer's own
environments.
Shared infrastructure: GitHub/Bitbucket and Ansible runners.

2. Deliverables
1. GCP infrastructure architecture design covering the four environments, the multi-
product and multi-customer model, version divergence and data sharing.
2. Three separate architecture diagrams: one each for Cloud Run, GKE and Instance
Group deployments.
3. Terraform scripts for infrastructure automation.
4. Helm charts for GKE deployment.
5. Documentation and code pushed to a public GitHub or Bitbucket repository, with the
link shared with us for review.
Use of AI tools: you may use AI tools for the design, diagrams, Terraform and Helm work.
Share your prompts log file (the prompts you used and the tools they ran in) along with
the repository link; we will use it as part of the evaluation.

Explain in in very simple language what this assisgnment is asking us to do ?
```

**Output:** a plain-language breakdown of the scenario, the six deliverables, and what the evaluators are likely testing. The assistant ended by offering to build the full submission.

## Prompt 2: Claude (claude.ai, agent mode)

```text
Yes , Please
```

(Accepting the assistant's offer from prompt 1: *"I can help you build it: plan the repo structure, write the design doc, draw the diagrams, write the Terraform modules and Helm charts, and keep the prompts log as we go."*)

**What the agent produced from this prompt** (the session ran tools for writing files, running Python and rendering Mermaid):

1. `docs/architecture.md`: hierarchy, tenancy tiers, IP plan, runtime patterns, version-divergence model, data-sharing model, security, scale and trade-offs.
2. Mermaid diagrams (overview, Cloud Run, GKE, MIG, data sharing), rendered to SVG and PNG with `mmdc` and visually checked. The GKE, overview, Cloud Run and data-sharing layouts were redrawn after the first renders came out cluttered.
3. The config model in `config/`, with two sample customers covering pooled vs dedicated GKE, a customer patch build, a Cloud Run canary and a MIG product.
4. Terraform: 8 modules and 7 stacks.
5. Helm charts `product-service` and `tenant-namespace`, the values layers, Argo CD ApplicationSets and AppProjects, and the shared Gateway.
6. Ansible, Packer, GitHub Actions, Bitbucket Pipelines, `tools/validate_config.py` and `tools/changed_tenants.py`.

**Corrections the agent made to its own output during the session** (kept here because they show the review loop):
- `allUsers` Cloud Run invoker → `invoker_iam_disabled`, because domain-restricted sharing would block `allUsers`.
- VPC-SC ingress from pooled GKE narrowed from "any service account" to the customer's own workload identities.
- Product service-account IDs changed to `<product>-sa`, since SA IDs need at least 6 characters.
- A wildcard `GCPBackendPolicy`, which isn't valid, replaced by one policy per Service in the chart.
- Separate `cicd-nonprod` and `cicd-prod` projects, since a service project can attach to only one Shared VPC host.
- PR plans limited to non-prod, since the prod Terraform identity is only reachable from the protected `prod` environment.

**Verification run in the session:** `tools/validate_config.py` passed, and was also run against deliberately broken config to confirm it catches errors. A custom static checker confirmed that every `var.`, `local.`, `module.`, `data.` and resource reference resolves and that module inputs and outputs match. All JSON and YAML parsed. Terraform and Helm binaries weren't available in that sandbox, so `terraform validate` and `helm lint` run in CI (`.github/workflows/ci.yml`) and locally before submission.

---

## Further prompts

<!-- Append each additional prompt here: number, date, tool (Claude / Claude Code / Copilot / Cursor …), the exact prompt text, and a one-line note on what was accepted or changed. -->

## My review notes

<!-- What I reviewed, changed or rejected from the AI output, and why. -->
