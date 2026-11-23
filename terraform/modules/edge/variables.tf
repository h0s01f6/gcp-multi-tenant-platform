variable "tier" {
  description = "prd or nonprd."
  type        = string
}

variable "domain" {
  description = "Base domain (A11 placeholder)."
  type        = string
}

variable "host_project" {
  description = "Host project holding the public zones (network stack)."
  type        = string
}

variable "ingress_project" {
  description = "plt-ingress-<tier>."
  type        = string
}

variable "gke_project" {
  description = "plt-gke-<tier> (Gateway certificate maps live with the clusters)."
  type        = string
}

variable "albs" {
  description = "build/edge.json albs of this tier."
  type        = any
}

variable "gateway_addresses" {
  description = "Gateway name -> {project, address, certificate}."
  type        = any
}

variable "certificates" {
  description = "Certificate key -> {domain, dns_authorization_zone}."
  type        = any
}

variable "records" {
  description = "A records [{hostname, zone, ttl, frontend}]."
  type        = any
}

variable "cloud_armor" {
  description = "Cloud Armor policies (network/edge.yaml)."
  type        = any
}

variable "uat_allowlist" {
  description = "Customer UAT source ranges (A-N4-3); empty means UAT denies everyone."
  type        = list(string)
  default     = []
}

variable "tls_profile" {
  description = "SSL policy profile."
  type        = string
  default     = "MODERN"
}

variable "min_tls_version" {
  description = "Minimum TLS version."
  type        = string
  default     = "TLS_1_2"
}
