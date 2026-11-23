variable "pool" {
  description = "Platform-stack pool entry: {pool, project, tier, env, edition, availability, database_version, kms_key, private_network, allocated_ip_range, ipv4_enabled, ssl_mode, connector_enforcement}."
  type        = any
}

variable "region" {
  description = "Region."
  type        = string
}

variable "host_project" {
  description = "Shared VPC host project."
  type        = string
}

variable "machine_tier" {
  description = "Machine type (capacity model; placeholder until Q22)."
  type        = string
  default     = "db-perf-optimized-N-4"
}

variable "dba_groups" {
  description = "Group e-mails allowed as IAM group database users (<= 3 per instance, AC06)."
  type        = list(string)
  default     = []
  validation {
    condition     = length(var.dba_groups) <= 3
    error_message = "At most 3 IAM groups per instance (design budget, AC06)."
  }
}

variable "dr" {
  description = "Stage 8: cross-region DR replica {region, kms_key}; null while regional DR is not activated (slo/dr.yaml)."
  type        = any
  default     = null
}
