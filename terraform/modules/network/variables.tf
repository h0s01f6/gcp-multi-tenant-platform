variable "tier" {
  description = "prd or nonprd."
  type        = string
  validation {
    condition     = contains(["prd", "nonprd"], var.tier)
    error_message = "tier must be prd or nonprd."
  }
}

variable "region" {
  description = "Active region (N1)."
  type        = string
}

variable "host_project" {
  description = "Shared VPC host project of the tier."
  type        = string
}

variable "group_domain" {
  description = "Domain of Cloud Identity groups."
  type        = string
}

variable "vpc" {
  description = "build/network-plan.json vpcs[tier]."
  type        = any
}

variable "subnets" {
  description = "Subnets of the tier (create = true) with secondary ranges."
  type        = any
}

variable "psa" {
  description = "PSA allocated range {range_name, cidr, service}."
  type        = any
}

variable "nat" {
  description = "build/edge.json nat entry for the tier."
  type        = any
}

variable "firewall_policy" {
  description = "build/firewall.json network_policies[fwp-<tier>]."
  type        = any
}

variable "secure_tags" {
  description = "build/firewall.json secure_tags[tier]."
  type        = any
}

variable "private_zones" {
  description = "Private DNS zones for Private Google Access."
  type        = any
}

variable "public_zones" {
  description = "Public zones per product for this tier."
  type        = any
}

variable "subnet_iam" {
  description = "[{subnet, role, member}] – Network User for grp-wl-netusers-<tier>."
  type        = any
}

variable "host_bindings" {
  description = "[{role, project, format}] – GKE host service agent user for cluster projects."
  type        = any
}
