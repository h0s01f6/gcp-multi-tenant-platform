variable "org_id" {
  description = "Organisation ID."
  type        = string
}

variable "folder_ids" {
  description = "Folder name -> folders/<id> (output of modules/folders)."
  type        = map(string)
}

variable "policies" {
  description = "From tools/iac/tfvars.py: [{node, constraint, kind (boolean|allow|deny|deny_all), enforce?, values?, dry_run}]."
  type        = any
}
