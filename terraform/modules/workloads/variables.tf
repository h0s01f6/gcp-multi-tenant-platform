variable "workloads" {
  description = "build/tfvars/{tenant,product}/<name>-<tier> (tools/iac/tfvars.py Bridge.workloads)."
  type        = any
}

variable "folder_ids" {
  description = "Folder name -> folders/<id> (org stack output)."
  type        = map(string)
}

variable "billing_account" {
  description = "Billing account ID."
  type        = string
}

variable "region" {
  description = "Region."
  type        = string
}

variable "host_project" {
  description = "Shared VPC host project of the tier."
  type        = string
}

variable "project_labels" {
  description = "Extra project labels (tenant, isolation_tier, cost_center)."
  type        = map(string)
  default     = {}
}

variable "app_port" {
  description = "Serving port of every workload (A-N3-1)."
  type        = number
  default     = 8080
}

variable "health_path" {
  description = "HTTP health-check path."
  type        = string
  default     = "/healthz"
}

variable "placeholder_image" {
  description = "Image for the first revision of a Cloud Run shell (release repository, by digest)."
  type        = string
}

variable "mig_machine_type" {
  description = "MIG machine type (capacity model)."
  type        = string
  default     = "e2-standard-2"
}

variable "mig_max_replicas" {
  description = "MIG autoscaler maximum."
  type        = number
  default     = 10
}
