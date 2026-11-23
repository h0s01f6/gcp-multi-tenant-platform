variable "name" {
  description = "Project ID (naming rules, registry/naming-rules.md)."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.name))
    error_message = "Invalid project ID."
  }
}

variable "folder_id" {
  description = "folders/<id> the project lives in."
  type        = string
}

variable "billing_account" {
  description = "Billing account ID."
  type        = string
}

variable "labels" {
  description = "Labels: tenant, product, env_tier, isolation_tier, deployment_model, cost_center (Stage 2 §0)."
  type        = map(string)
  default     = {}
}

variable "apis" {
  description = "Services to enable."
  type        = list(string)
  default     = []
}

variable "host_project" {
  description = "Shared VPC host project of the tier, or null when the project runs no VPC workload."
  type        = string
  default     = null
}
