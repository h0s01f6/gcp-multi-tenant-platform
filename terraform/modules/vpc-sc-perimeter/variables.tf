variable "access_policy_id" { type = string }
variable "name" {
  type        = string
  description = "Perimeter name, letters/digits/underscores only, e.g. tenant_acme."
}
variable "project_numbers" { type = list(string) }
variable "restricted_services" {
  type = list(string)
  default = [
    "bigquery.googleapis.com", "storage.googleapis.com", "sqladmin.googleapis.com",
    "secretmanager.googleapis.com", "cloudkms.googleapis.com",
  ]
}
variable "ingress_source_projects" {
  type        = list(string)
  default     = []
  description = "Project numbers whose networks may call in (Shared VPC host projects used by pooled GKE)."
}
variable "workload_identities" {
  type        = list(string)
  default     = []
  description = "serviceAccount:<product>@<customer project>... identities of this customer's workloads."
}
variable "admin_identities" {
  type    = list(string)
  default = []
}
variable "dry_run" {
  type    = bool
  default = true
}
