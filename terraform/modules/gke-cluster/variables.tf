variable "project_id" { type = string }
variable "name" { type = string }
variable "region" { type = string }
variable "network" { type = string }
variable "subnetwork" { type = string }
variable "pods_range_name" { type = string }
variable "services_range_name" { type = string }
variable "master_cidr" { type = string }
variable "master_authorized_networks" {
  type        = map(string)
  default     = {}
  description = "name => CIDR allowed to reach the control plane (CI runners, VPN)."
}
variable "release_channel" {
  type    = string
  default = "REGULAR"
}
variable "maintenance_recurrence" {
  type    = string
  default = "FREQ=WEEKLY;BYDAY=SA,SU"
}
variable "deletion_protection" {
  type    = bool
  default = true
}
variable "labels" {
  type    = map(string)
  default = {}
}
variable "node_pools" {
  type = map(object({
    machine_type = string
    min          = number
    max          = number
    spot         = optional(bool, false)
    labels       = optional(map(string), {})
    taints       = optional(list(object({ key = string, value = string })), [])
  }))
}
