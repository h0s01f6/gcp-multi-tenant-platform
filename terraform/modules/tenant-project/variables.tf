variable "project_id" { type = string }
variable "folder_id" { type = string }
variable "billing_account" { type = string }
variable "env_tag_value_id" {
  type        = string
  description = "tagValues/<id> of the env tag to bind."
}
variable "labels" {
  type    = map(string)
  default = {}
}
variable "apis" {
  type = list(string)
  default = [
    "compute.googleapis.com", "container.googleapis.com", "run.googleapis.com",
    "iam.googleapis.com", "secretmanager.googleapis.com", "sqladmin.googleapis.com",
    "logging.googleapis.com", "monitoring.googleapis.com", "artifactregistry.googleapis.com",
  ]
}
variable "host_project_id" {
  type        = string
  default     = null
  description = "Shared VPC host project; null = do not attach."
}
variable "budget_usd" {
  type    = number
  default = null
}
variable "support_group" {
  type    = string
  default = null
}
variable "support_roles" {
  type    = list(string)
  default = []
}
variable "deletion_policy" {
  type    = string
  default = "PREVENT"
}
