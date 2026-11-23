variable "org_id" {
  description = "Organisation ID."
  type        = string
}

variable "folders" {
  description = "Folder nodes from security/org-policies.yaml: [{name, parent}] with parent 'org' or a top-level folder."
  type        = list(object({ name = string, parent = string }))
}
