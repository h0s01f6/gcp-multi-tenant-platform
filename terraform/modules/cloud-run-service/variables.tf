variable "project_id" { type = string }
variable "region" { type = string }
variable "name" { type = string }
variable "image_repo" {
  type        = string
  description = "Image without tag, e.g. <registry>/notify. Production pipelines pin by digest."
}
variable "version_tag" { type = string }
variable "canary" {
  type = object({
    version = string
    percent = number
  })
  default = null
}
variable "service_account" { type = string }
variable "network" { type = string }
variable "subnetwork" { type = string }
variable "port" {
  type    = number
  default = 8080
}
variable "cpu" {
  type    = string
  default = "1"
}
variable "memory" {
  type    = string
  default = "512Mi"
}
variable "min_instances" {
  type    = number
  default = 0
}
variable "max_instances" {
  type    = number
  default = 10
}
variable "env" {
  type    = map(string)
  default = {}
}
variable "labels" {
  type    = map(string)
  default = {}
}
variable "allow_lb_unauthenticated" {
  type    = bool
  default = true
}
variable "deletion_protection" {
  type    = bool
  default = true
}
