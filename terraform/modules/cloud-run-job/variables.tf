variable "job" {
  description = "build/network-plan.json cloud_run job entry {job, project, network, subnet, egress, network_tags}."
  type        = any
}

variable "service_account" {
  description = "Job identity (sqlboot-<tier>@plt-sql-<tier>-NN or isotest-<tier>@shr-cicd-<tier>)."
  type        = string
}

variable "region" {
  description = "Region."
  type        = string
}

variable "host_project" {
  description = "Shared VPC host project."
  type        = string
}

variable "image" {
  description = "Initial image (release repository, by digest); later versions are set by the pipeline."
  type        = string
}
