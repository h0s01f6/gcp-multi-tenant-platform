variable "tier" {
  description = "prd or nonprd."
  type        = string
}

variable "domain" {
  description = "Base domain."
  type        = string
}

variable "host_project" {
  description = "Host project (zones)."
  type        = string
}

variable "ingress_project" {
  description = "plt-ingress-<tier>."
  type        = string
}

variable "gke_project" {
  description = "plt-gke-<tier>."
  type        = string
}

variable "albs" {
  description = "ALBs."
  type        = any
}

variable "gateway_addresses" {
  description = "Gateway addresses."
  type        = any
}

variable "certificates" {
  description = "Certificates."
  type        = any
}

variable "records" {
  description = "DNS records."
  type        = any
}

variable "cloud_armor" {
  description = "Cloud Armor policies."
  type        = any
}

variable "uat_allowlist" {
  description = "UAT allow-list (A-N4-3)."
  type        = list(string)
  default     = []
}
