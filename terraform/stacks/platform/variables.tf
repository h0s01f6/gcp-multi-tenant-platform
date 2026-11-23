variable "tier" {
  description = "prd or nonprd."
  type        = string
}

variable "region" {
  description = "Region."
  type        = string
}

variable "host_project" {
  description = "Host project."
  type        = string
}

variable "billing_account" {
  description = "Billing account."
  type        = string
}

variable "projects" {
  description = "Platform and product projects of the tier."
  type        = any
}

variable "gke_cells" {
  description = "GKE cells."
  type        = any
}

variable "sql_pools" {
  description = "Cloud SQL pools."
  type        = any
}

variable "pool_keys" {
  description = "Pool CMEK keys."
  type        = any
}

variable "dba_group_users" {
  description = "IAM group users per pool."
  type        = any
}

variable "jobs" {
  description = "db-bootstrap / db-isotest jobs."
  type        = any
}

variable "binauthz_policies" {
  description = "Binary Authorization policies for platform projects."
  type        = any
}

variable "job_image" {
  description = "Initial image of the platform jobs (release repository, by digest)."
  type        = string
  default     = "asia-south1-docker.pkg.dev/shr-artifacts/release/platform/db-tools@sha256:0000000000000000000000000000000000000000000000000000000000000000"
}

variable "org_state_bucket" {
  description = "Bucket holding the org stack state (tfstate-org-<suffix>)."
  type        = string
}
