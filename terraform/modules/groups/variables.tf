variable "customer_id" {
  description = "Cloud Identity customer id."
  type        = string
}

variable "group_domain" {
  description = "Group e-mail domain."
  type        = string
}

variable "groups" {
  description = "Groups to create (org stack); empty in the memberships stack."
  type        = map(any)
  default     = {}
}

variable "manage_groups" {
  description = "True when this stack creates the groups."
  type        = bool
  default     = true
}

variable "memberships" {
  description = "[{group, member (type:email), manager?}]."
  type        = any
  default     = []
}
