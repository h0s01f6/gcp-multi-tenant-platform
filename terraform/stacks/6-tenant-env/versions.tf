terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.10, < 7.0"
    }
  }
  # Partial config: bucket/prefix are passed by CI, e.g.
  #   terraform init -backend-config="bucket=mtp-tfstate" -backend-config="prefix=<stack path>"
  backend "gcs" {}
}

provider "google" {
  # Impersonate the Terraform SA created in 0-bootstrap; CI obtains it via WIF.
  impersonate_service_account = var.terraform_sa
  user_project_override       = true
  billing_project             = var.billing_project
}
