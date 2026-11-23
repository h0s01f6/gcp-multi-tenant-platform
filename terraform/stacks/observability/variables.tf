variable "tier" {
  description = "prd or nonprd."
  type        = string
}

variable "billing_account" {
  description = "Billing account."
  type        = string
}

variable "scoping_projects" {
  description = "plt-obs-<tier>-NN projects {name, folder}."
  type        = any
}

variable "monitored_projects" {
  description = "{scope, project}: every project of the tier in exactly one metrics scope (SL06)."
  type        = any
}

variable "channels" {
  description = "Notification channels {scope, id, type, address}."
  type        = any
}

variable "log_metrics" {
  description = "Log-based SLI metrics of Shared / Cohort products {project, name, kind, filter, labels, value_extractor}."
  type        = any
}

variable "services" {
  description = "Custom services {scope, id, product} (one per product, sharded)."
  type        = any
}

variable "slos" {
  description = "SLOs per customer per product (prd)."
  type        = any
}

variable "alert_policies" {
  description = "Alert policies {scope, id, display_name, severity, conditions, channels}."
  type        = any
}

variable "dashboards" {
  description = "Dashboards {scope, id, json}."
  type        = any
}

variable "org_state_bucket" {
  description = "Bucket holding the org stack state (tfstate-org-<suffix>)."
  type        = string
}
