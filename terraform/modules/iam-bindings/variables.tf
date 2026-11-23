variable "bindings" {
  description = "[{scope_type, scope, role, member, condition}] from tools/iac/tfvars.py (access matrix, D3)."
  type = list(object({
    scope_type = string
    scope      = string
    role       = string
    member     = string
    condition  = optional(string)
  }))
  validation {
    condition     = alltrue([for b in var.bindings : !contains(["roles/owner", "roles/editor", "roles/viewer"], b.role)])
    error_message = "Legacy basic roles are forbidden (AC02)."
  }
}

variable "org_id" {
  description = "Organisation ID."
  type        = string
}

variable "billing_account" {
  description = "Billing account ID."
  type        = string
}

variable "folder_ids" {
  description = "Folder name -> folders/<id>."
  type        = map(string)
  default     = {}
}
