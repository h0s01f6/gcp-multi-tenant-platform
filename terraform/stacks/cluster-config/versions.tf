terraform {
  required_version = ">= 1.6.0"
  backend "gcs" {} # tfstate-<tier>/cluster-config/<cell>
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 8.0" # pin exactly after the first `terraform init` (T-TF1)
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.30, < 3.0"
    }
  }
}
