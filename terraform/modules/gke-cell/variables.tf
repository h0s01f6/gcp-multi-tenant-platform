variable "project" {
  description = "Cluster project (plt-gke-<tier>)."
  type        = string
}

variable "host_project" {
  description = "Shared VPC host project."
  type        = string
}

variable "region" {
  description = "Region of the regional Autopilot cluster."
  type        = string
}

variable "env" {
  description = "Environment served by the cell (dev, stg, uat, prd)."
  type        = string
}

variable "cell" {
  description = "build/network-plan.json gke_clusters entry."
  type        = any
}

variable "release_channel" {
  description = "GKE release channel (prod REGULAR, non-prod RAPID is not used: same channel keeps versions aligned)."
  type        = string
  default     = "REGULAR"
}

variable "disable_ip_endpoint" {
  description = "Disable the IP-based control-plane endpoint entirely once T-N7 confirms DNS endpoint access."
  type        = bool
  default     = false
}
