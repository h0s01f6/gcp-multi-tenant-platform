variable "org_id" {
  description = "Organisation ID."
  type        = string
}

variable "folder_ids" {
  description = "Folder name -> folders/<id>; matrix folder scopes are passed as fldr-<x>/<tier> by the org stack."
  type        = map(string)
}

variable "entitlements" {
  description = "build/pam-entitlements.json."
  type        = any
}
