variable "host_project_id" { type = string }
variable "network" { type = string }
variable "name" { type = string }
variable "region" { type = string }
variable "cidr" { type = string }
variable "secondary_ranges" {
  type    = map(string)
  default = {}
}
variable "network_users" {
  type        = list(string)
  description = "IAM members (serviceAccount:..., group:...) granted networkUser on this subnet only."
}
