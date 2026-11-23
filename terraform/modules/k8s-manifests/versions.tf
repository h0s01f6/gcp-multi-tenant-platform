terraform {
  required_version = ">= 1.6.0"
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.30, < 3.0" # pin exactly after the first `terraform init` (T-TF1)
    }
  }
}
