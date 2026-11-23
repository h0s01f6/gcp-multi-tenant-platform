variable "cell" {
  description = "Cell (cluster) name."
  type        = string
}

variable "project" {
  description = "Cluster project."
  type        = string
}

variable "region" {
  description = "Region."
  type        = string
}

variable "manifests_dir" {
  description = "Rendered D8 manifests for the cell, relative to the repository root."
  type        = string
}

variable "gateways" {
  description = "Gateways of the cell (build/edge.json)."
  type        = any
}

variable "repo_root" {
  description = "Repository root as seen by the pipeline."
  type        = string
  default     = "../../.."
}
