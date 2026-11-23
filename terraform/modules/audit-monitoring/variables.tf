variable "org_id" {
  description = "Organisation ID."
  type        = string
}

variable "folder_ids" {
  description = "Folder name -> folders/<id>."
  type        = map(string)
}

variable "audit" {
  description = "build/monitoring.json subset: audit_configs, log_bucket, sink, channels, alert_policies."
  type        = any
}
