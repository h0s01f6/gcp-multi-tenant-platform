terraform {
  required_version = ">= 1.6.0"
  backend "gcs" {} # bucket + prefix from -backend-config (terraform/stacks.yaml: tfstate-<tier>/observability)
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 8.0" # pin exactly after the first `terraform init` (T-TF1)
    }
  }
}
