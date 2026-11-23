# Terraform (Stage 5)

Status: **implemented and statically checked** (`tools/iac/hclcheck.py`, `tools/iac/stacks.py`, tfvars bridge tests). **Not run**: no `terraform` binary or GCP organisation is available here (T-TF1–T-TF6).

```
terraform/
  stacks.yaml          stack catalogue: state, identity, required IAM, creates, apply order
  modules/             18 reusable modules (no per-customer data in them)
  stacks/              9 root modules = state units: bootstrap, org, network, platform, edge, cluster-config,
                       tenant, product, memberships
```

Inputs are **generated**: `python3 -m tools.iac.tfvars` writes `build/tfvars/<stack>/<instance>.auto.tfvars.json` from the registry and the Stage 2–4 plans. A stack instance is applied with:

```bash
cd terraform/stacks/tenant
terraform init -backend-config="bucket=tfstate-prd-<suffix>" -backend-config="prefix=tenants/abc"
terraform apply -var-file=../../../build/tfvars/tenant/abc-prd.auto.tfvars.json -var org_state_bucket=tfstate-org-<suffix>
```

| Module | Purpose | Main inputs (generated) |
|---|---|---|
| folders, org-policies, firewall-hierarchical | Folder tree, D5 guardrails, N3 org/tier firewall | D5 yaml, `build/firewall.json` |
| iam-bindings | Additive IAM for every scope type of the access matrix | D3 bindings |
| groups | Cloud Identity groups, manager and pipeline/workload memberships | D3, D2, N2 |
| wif, pam, audit-monitoring, binauthz-attestor | D6, D7, D10, D9 | generated JSON |
| project | Project, APIs, labels, Shared VPC attachment | registry |
| network | VPC, subnets, PSA, NAT, network firewall policy, secure tags, DNS zones, subnet IAM | N1–N4 |
| gke-cell, sql-pool, kms, cloud-run-job | Platform runtimes | N2, D4, D9 |
| workloads | Everything in one customer / product project | D2, D4, D9, N2, N4 |
| edge | Cloud Armor, certificates, ALBs / URL maps, Gateway addresses, DNS records | N4 |
| k8s-manifests | D8 baselines, Policy Controller templates, Gateways (Kubernetes provider) | `build/k8s/<cell>` |

Principles: Terraform owns infrastructure and **platform** Kubernetes objects; application images and versions are never managed by Terraform (Cloud Run images and MIG source images are `ignore_changes`; GKE apps are Helm). No secret values in state (no secret versions – HC07). Every identity runs only its own stack (`stacks.yaml` `requires`, checked against the access matrix – SK02).
