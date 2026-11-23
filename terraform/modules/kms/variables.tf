variable "keys" {
  description = "build/data-protection.json keys (agents as {project, format})."
  type        = any
}

variable "create_key_rings" {
  description = "Create the key rings (tenant stack) or use existing ones (platform keys: rings created by the org stack)."
  type        = bool
  default     = true
}
