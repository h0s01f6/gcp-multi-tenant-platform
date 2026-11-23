variable "org_id" {
  description = "Organisation ID."
  type        = string
}

variable "billing_account" {
  description = "Billing account ID."
  type        = string
}

variable "region" {
  description = "Region of the state buckets."
  type        = string
  default     = "asia-south1"
}

variable "state_bucket_suffix" {
  description = "Globally unique suffix for bucket names."
  type        = string
}
