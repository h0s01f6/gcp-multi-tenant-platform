variable "tier" {
  description = "prd or nonprd."
  type        = string
}

variable "group_domain" {
  description = "Group domain."
  type        = string
}

variable "memberships" {
  description = "[{group, member | project+format}] (D2 plan + N2 service agents)."
  type        = any
}
