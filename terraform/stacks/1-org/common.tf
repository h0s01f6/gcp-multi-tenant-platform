variable "terraform_sa" {
  type        = string
  description = "Terraform service account to impersonate (from 0-bootstrap)."
}
variable "billing_project" {
  type        = string
  description = "Quota/billing project for API calls (the seed project)."
}
variable "state_bucket" {
  type        = string
  description = "GCS bucket holding all Terraform state (from 0-bootstrap)."
}

locals {
  config_dir = "${path.module}/../../../config"
  platform   = yamldecode(file("${local.config_dir}/platform.yaml"))
  prefix     = local.platform.prefix
  envs       = local.platform.environments
}
