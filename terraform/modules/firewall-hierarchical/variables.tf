variable "org_id" {
  description = "Organisation ID."
  type        = string
}

variable "folder_ids" {
  description = "Folder name -> folders/<id>."
  type        = map(string)
}

variable "policies" {
  description = "build/firewall.json `hierarchical`: {name: {attach, rules[{priority, direction, action, src|dst, ports}]}}."
  type        = any
}
