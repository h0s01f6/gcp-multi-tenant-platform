variable "project_id" { type = string }
variable "region" { type = string }
variable "name" { type = string }
variable "version_tag" { type = string }
variable "source_image" {
  type        = string
  description = "Golden image self link, baked by Packer + Ansible per version."
}
variable "machine_type" {
  type    = string
  default = "e2-standard-2"
}
variable "disk_size_gb" {
  type    = number
  default = 50
}
variable "subnetwork" { type = string }
variable "subnetwork_project" { type = string }
variable "service_account" { type = string }
variable "network_tags" {
  type    = list(string)
  default = []
}
variable "port" {
  type    = number
  default = 8080
}
variable "health_path" {
  type    = string
  default = "/healthz"
}
variable "min_replicas" {
  type    = number
  default = 1
}
variable "max_replicas" {
  type    = number
  default = 3
}
variable "metadata" {
  type    = map(string)
  default = {}
}
variable "labels" {
  type    = map(string)
  default = {}
}
