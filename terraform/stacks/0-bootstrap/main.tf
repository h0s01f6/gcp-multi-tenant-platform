# Run once by an org admin with local state, then migrate state into the bucket:
#   terraform init && terraform apply
#   terraform init -migrate-state -backend-config="bucket=<state_bucket>" -backend-config="prefix=0-bootstrap"
terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.10, < 7.0"
    }
  }
}

locals {
  platform = yamldecode(file("${path.module}/../../../config/platform.yaml"))
  prefix   = local.platform.prefix
}

resource "google_folder" "platform" {
  display_name = "fldr-platform"
  parent       = "organizations/${local.platform.org_id}"
}

resource "google_project" "seed" {
  project_id          = "${local.prefix}-seed"
  name                = "${local.prefix}-seed"
  folder_id           = google_folder.platform.name
  billing_account     = local.platform.billing_account
  auto_create_network = false
}

resource "google_project_service" "seed" {
  for_each = toset([
    "cloudresourcemanager.googleapis.com", "cloudbilling.googleapis.com", "iam.googleapis.com",
    "serviceusage.googleapis.com", "storage.googleapis.com", "accesscontextmanager.googleapis.com",
    "orgpolicy.googleapis.com", "billingbudgets.googleapis.com", "compute.googleapis.com",
    "container.googleapis.com", "iamcredentials.googleapis.com", "sts.googleapis.com",
  ])
  project            = google_project.seed.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_storage_bucket" "state" {
  project                     = google_project.seed.project_id
  name                        = "${local.prefix}-tfstate"
  location                    = "ASIA-SOUTH1"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  versioning {
    enabled = true
  }
  lifecycle_rule {
    condition {
      num_newer_versions = 20
    }
    action {
      type = "Delete"
    }
  }
}

# Two Terraform identities: prod and non-prod. Prod can only be impersonated from
# the prod CI pipeline (see 3-platform WIF bindings), limiting blast radius.
resource "google_service_account" "tf" {
  for_each     = toset(["nonprod", "prod"])
  project      = google_project.seed.project_id
  account_id   = "tf-${each.key}"
  display_name = "Terraform ${each.key}"
}

resource "google_storage_bucket_iam_member" "state" {
  for_each = google_service_account.tf
  bucket   = google_storage_bucket.state.name
  role     = "roles/storage.objectAdmin"
  member   = "serviceAccount:${each.value.email}"
}

# Org-level roles. In a stricter setup the non-prod SA would be scoped to non-prod folders only.
resource "google_organization_iam_member" "tf" {
  for_each = {
    for pair in setproduct(keys(google_service_account.tf), [
      "roles/resourcemanager.folderAdmin", "roles/resourcemanager.projectCreator",
      "roles/compute.xpnAdmin", "roles/orgpolicy.policyAdmin", "roles/resourcemanager.tagAdmin",
      "roles/resourcemanager.tagUser", "roles/accesscontextmanager.policyAdmin",
      "roles/billing.projectManager", "roles/iam.securityAdmin", "roles/logging.configWriter",
    ]) : "${pair[0]}-${pair[1]}" => { sa = pair[0], role = pair[1] }
  }
  org_id = local.platform.org_id
  role   = each.value.role
  member = "serviceAccount:${google_service_account.tf[each.value.sa].email}"
}

resource "google_billing_account_iam_member" "tf" {
  for_each           = google_service_account.tf
  billing_account_id = local.platform.billing_account
  role               = "roles/billing.user"
  member             = "serviceAccount:${each.value.email}"
}

# Org-wide VPC Service Controls access policy (one per org).
resource "google_access_context_manager_access_policy" "this" {
  parent = "organizations/${local.platform.org_id}"
  title  = "${local.prefix}-org-policy"
}

output "seed_project_id" { value = google_project.seed.project_id }
output "state_bucket" { value = google_storage_bucket.state.name }
output "platform_folder_id" { value = google_folder.platform.name }
output "terraform_sa" { value = { for k, v in google_service_account.tf : k => v.email } }
output "access_policy_id" { value = google_access_context_manager_access_policy.this.name }
