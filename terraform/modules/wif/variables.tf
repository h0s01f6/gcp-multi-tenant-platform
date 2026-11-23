variable "pool" {
  description = "{project, id} of the WIF pool (security/cicd-identities.yaml)."
  type        = object({ project = string, id = string })
}

variable "providers_config" {
  description = "Enabled providers: {name: {issuer, attribute_condition, attribute_mapping}}."
  type        = any
}

variable "repository_ids" {
  description = "Repository name -> numeric GitHub repository id (security/cicd-identities.yaml repositories)."
  type        = map(string)
}

variable "bindings" {
  description = "[{service_account, gates[{repo, env, ref}]}] (D6 attribute.gate values)."
  type        = any
}

variable "github_org_id" {
  description = "Numeric GitHub organisation id (CI02)."
  type        = string
}

variable "github_org" {
  description = "GitHub organisation name (central reusable workflows)."
  type        = string
}
