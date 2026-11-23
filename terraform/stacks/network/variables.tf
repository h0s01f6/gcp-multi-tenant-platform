variable "tier" {
  description = "prd or nonprd."
  type        = string
}

variable "region" {
  description = "Region."
  type        = string
}

variable "host_project" {
  description = "Host project."
  type        = string
}

variable "group_domain" {
  description = "Group domain."
  type        = string
}

variable "vpc" {
  description = "VPC settings."
  type        = any
}

variable "subnets" {
  description = "Subnets."
  type        = any
}

variable "psa" {
  description = "PSA range."
  type        = any
}

variable "nat" {
  description = "Cloud NAT."
  type        = any
}

variable "firewall_policy" {
  description = "Network firewall policy."
  type        = any
}

variable "secure_tags" {
  description = "Secure tags."
  type        = any
}

variable "private_zones" {
  description = "Private DNS zones."
  type        = any
}

variable "public_zones" {
  description = "Public DNS zones."
  type        = any
}

variable "subnet_iam" {
  description = "Subnet IAM."
  type        = any
}

variable "host_bindings" {
  description = "Host project bindings for service agents."
  type        = any
}
