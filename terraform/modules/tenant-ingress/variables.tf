variable "project_id" { type = string }
variable "name" { type = string }
variable "backends" {
  description = "product => { host, type = serverless|mig, group, health_check }"
  type = map(object({
    host         = string
    type         = string
    group        = string
    health_check = optional(string)
  }))
  validation {
    condition     = length(var.backends) > 0 && alltrue([for b in values(var.backends) : contains(["serverless", "mig"], b.type)])
    error_message = "At least one backend; type must be serverless or mig."
  }
}
