# Generated inputs: build/tfvars/org/org.auto.tfvars.json (tools/iac/tfvars.py). Secrets are never inputs.
variable "org_id" {
  description = "Organisation ID."
  type        = string
}

variable "billing_account" {
  description = "Billing account ID."
  type        = string
}

variable "customer_id" {
  description = "Cloud Identity customer id."
  type        = string
}

variable "region" {
  description = "Primary region."
  type        = string
}

variable "group_domain" {
  description = "Group e-mail domain."
  type        = string
}

variable "folders" {
  description = "Folder tree."
  type        = list(object({ name = string, parent = string }))
}

variable "org_policies" {
  description = "D5 policies."
  type        = any
}

variable "hierarchical_firewall_policies" {
  description = "N3 hierarchical policies."
  type        = any
}

variable "groups" {
  description = "D3 group catalogue (expanded)."
  type        = map(any)
}

variable "iam_bindings" {
  description = "D3 bindings owned by this stack."
  type        = any
}

variable "group_managers" {
  description = "Group manager memberships (D3/D7)."
  type        = any
}

variable "pipeline_memberships" {
  description = "Pipeline group memberships (D3)."
  type        = any
}

variable "kms_keyrings" {
  description = "Key rings created centrally (attestor, pool keys)."
  type        = any
}

variable "pam_entitlements" {
  description = "D7 entitlements."
  type        = any
}

variable "wif" {
  description = "D6 pool, providers, repository ids, bindings."
  type        = any
}

variable "audit" {
  description = "D10 audit configuration and alerts."
  type        = any
}

variable "shared_projects" {
  description = "Shared projects in fldr-shared."
  type        = list(string)
}

variable "host_projects" {
  description = "Shared VPC host projects in fldr-network."
  type        = list(string)
}

variable "artifact_repositories" {
  description = "Artifact Registry repositories (ADR-010)."
  type        = list(string)
}

variable "attestor" {
  description = "D9 attestor."
  type        = any
}

variable "github_org_id" {
  description = "Numeric GitHub organisation id (TF_VAR_github_org_id from the org pipeline)."
  type        = string
}

variable "github_org" {
  description = "GitHub organisation name."
  type        = string
}

variable "repository_ids" {
  description = "Repository name -> numeric id (TF_VAR_repository_ids); overrides the placeholders."
  type        = map(string)
  default     = {}
}
