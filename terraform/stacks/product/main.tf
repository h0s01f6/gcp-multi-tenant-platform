# Product stack (tf-<tier>), one state per product per tier. Input: build/tfvars/product/<name>-<tier>.
provider "google" {}

data "terraform_remote_state" "org" {
  backend = "gcs"
  config = {
    bucket = var.org_state_bucket
    prefix = "org"
  }
}

module "workloads" {
  source            = "../../modules/workloads"
  workloads         = var.workloads
  folder_ids        = data.terraform_remote_state.org.outputs.folder_ids
  billing_account   = var.billing_account
  region            = var.region
  host_project      = var.host_project
  placeholder_image = var.placeholder_image
}
