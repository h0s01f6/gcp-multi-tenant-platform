# The only stack applied by hand (Stage 2: bootstrap-seed is the only hand-made project). Creates the seed project,
# the per-tier state buckets (ADR-010) and the identities the other stacks run as. Everything else is pipelines.
provider "google" {}

resource "google_folder" "bootstrap" {
  display_name = "fldr-bootstrap"
  parent       = "organizations/${var.org_id}"
}

module "seed" {
  source          = "../../modules/project"
  name            = "bootstrap-seed"
  folder_id       = google_folder.bootstrap.name
  billing_account = var.billing_account
  labels          = { purpose = "bootstrap" }
  apis = ["iam.googleapis.com", "iamcredentials.googleapis.com", "sts.googleapis.com", "storage.googleapis.com",
  "cloudresourcemanager.googleapis.com", "orgpolicy.googleapis.com", "cloudidentity.googleapis.com"]
}

resource "google_storage_bucket" "state" {
  for_each                    = toset(["tfstate-org", "tfstate-prd", "tfstate-nonprd"])
  project                     = module.seed.project_id
  name                        = "${each.key}-${var.state_bucket_suffix}"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  versioning {
    enabled = true
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_service_account" "tf" {
  for_each   = toset(["tf-org", "tf-plan-org"])
  project    = module.seed.project_id
  account_id = each.key
}
