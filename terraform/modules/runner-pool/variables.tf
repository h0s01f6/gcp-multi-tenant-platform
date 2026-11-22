variable "project_id" { type = string }
variable "region" { type = string }
variable "name" { type = string }
variable "machine_type" {
  type    = string
  default = "e2-standard-4"
}
variable "source_image" {
  type    = string
  default = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64"
}
variable "subnetwork" { type = string }
variable "subnetwork_project" { type = string }
variable "startup_script" { type = string }
variable "registration_secret_id" {
  type    = string
  default = null
}
variable "min_replicas" {
  type    = number
  default = 1
}
variable "max_replicas" {
  type    = number
  default = 10
}
variable "labels" {
  type    = map(string)
  default = {}
}
