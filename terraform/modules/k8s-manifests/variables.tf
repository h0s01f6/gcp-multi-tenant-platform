variable "manifests_dir" {
  description = "build/k8s/<cell> rendered by tools/k8s/baseline.py (namespace baselines + _cluster.yaml)."
  type        = string
}

variable "constraint_templates_file" {
  description = "policies/k8s/constraint-templates.yaml (D8)."
  type        = string
}

variable "gateways" {
  description = "build/edge.json gateways of this cell."
  type        = any
}
