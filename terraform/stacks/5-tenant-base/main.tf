# Per customer (state prefix: tenants/<customer>/base):
#   customer folder, 4 environment projects, data project, CMEK, shared datasets/buckets,
#   and the customer's VPC Service Controls perimeter.
variable "customer" {
  type        = string
  description = "Customer slug = directory name under config/tenants/."
}

data "terraform_remote_state" "bootstrap" {
  backend = "gcs"
  config  = { bucket = var.state_bucket, prefix = "0-bootstrap" }
}
data "terraform_remote_state" "org" {
  backend = "gcs"
  config  = { bucket = var.state_bucket, prefix = "1-org" }
}
data "terraform_remote_state" "net" {
  backend = "gcs"
  config  = { bucket = var.state_bucket, prefix = "2-networking" }
}

locals {
  tenant_dir = "${local.config_dir}/tenants/${var.customer}"
  tenant     = yamldecode(file("${local.tenant_dir}/tenant.yaml"))
  region     = try(local.tenant.region, local.platform.default_region)
  org        = data.terraform_remote_state.org.outputs
  net        = data.terraform_remote_state.net.outputs
  labels     = { customer = var.customer }

  # Every <env>/<product>.yaml release file of this customer.
  release_files = [for f in fileset(local.tenant_dir, "*/*.yaml") : f if contains(keys(local.envs), dirname(f))]
  releases      = [for f in local.release_files : yamldecode(file("${local.tenant_dir}/${f}"))]

  # Deterministic workload identities, used by the perimeter before tenant-env creates them.
  workload_identities = distinct([
    for r in local.releases : "serviceAccount:${r.product}-sa@${local.prefix}-${var.customer}-${r.env}.iam.gserviceaccount.com"
  ])
  pooled_envs = [for env, g in local.tenant.gke : env if g.mode == "pooled"]
}

resource "google_folder" "customer" {
  display_name = "fldr-${var.customer}"
  parent       = local.org.folders["tenants"]
}

module "env_project" {
  source   = "../../modules/tenant-project"
  for_each = local.envs

  project_id       = "${local.prefix}-${var.customer}-${each.key}"
  folder_id        = google_folder.customer.name
  billing_account  = local.platform.billing_account
  env_tag_value_id = local.org.env_tag_values[each.key]
  host_project_id  = local.net.host_projects[each.key]
  budget_usd       = try(local.tenant.budgets_usd[each.key], null)
  labels           = merge(local.labels, { env = each.key })
  support_group    = try(local.tenant.access.support_group, null)
  support_roles    = each.key == "prod" ? ["roles/logging.viewer", "roles/monitoring.viewer"] : ["roles/viewer"]
}

# Data project holds prod-derived data, so it carries the prod tag (CMEK enforced).
module "data_project" {
  source = "../../modules/tenant-project"

  project_id       = "${local.prefix}-${var.customer}-data"
  folder_id        = google_folder.customer.name
  billing_account  = local.platform.billing_account
  env_tag_value_id = local.org.env_tag_values["prod"]
  labels           = merge(local.labels, { env = "shared", role = "data" })
  apis = [
    "bigquery.googleapis.com", "storage.googleapis.com", "cloudkms.googleapis.com",
    "dlp.googleapis.com", "iam.googleapis.com",
  ]
}

# ---------------- Customer CMEK (crypto-shredding on offboarding) ----------------
resource "google_kms_key_ring" "customer" {
  project  = module.data_project.project_id
  name     = var.customer
  location = local.region
}

resource "google_kms_crypto_key" "data" {
  for_each        = toset(["bigquery", "storage"])
  name            = each.key
  key_ring        = google_kms_key_ring.customer.id
  rotation_period = "7776000s" # 90 days
  lifecycle {
    prevent_destroy = true
  }
}

data "google_storage_project_service_account" "gcs" {
  project = module.data_project.project_id
}
data "google_bigquery_default_service_account" "bq" {
  project = module.data_project.project_id
}

resource "google_kms_crypto_key_iam_member" "agents" {
  for_each = {
    bigquery = "serviceAccount:${data.google_bigquery_default_service_account.bq.email}"
    storage  = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
  }
  crypto_key_id = google_kms_crypto_key.data[each.key].id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = each.value
}

# ---------------- Cross-environment data zones (this customer only) ----------------
locals {
  zones = {
    raw_prod         = "Raw export from prod; prod only unless raw_from_prod_to allows"
    masked           = "De-identified copy of prod data for lower environments"
    shared_reference = "Reference/master data readable by all environments"
  }
}

resource "google_bigquery_dataset" "zone" {
  for_each    = local.zones
  project     = module.data_project.project_id
  dataset_id  = each.key
  location    = local.region
  description = each.value
  labels      = merge(local.labels, { zone = each.key })

  default_encryption_configuration {
    kms_key_name = google_kms_crypto_key.data["bigquery"].id
  }
  depends_on = [google_kms_crypto_key_iam_member.agents]
}

resource "google_storage_bucket" "zone" {
  for_each                    = local.zones
  project                     = module.data_project.project_id
  name                        = "${local.prefix}-${var.customer}-${replace(each.key, "_", "-")}"
  location                    = upper(local.region)
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = merge(local.labels, { zone = each.key })

  encryption {
    default_kms_key_name = google_kms_crypto_key.data["storage"].id
  }
  versioning {
    enabled = each.key == "raw_prod"
  }
  depends_on = [google_kms_crypto_key_iam_member.agents]
}

# The de-identification job (Sensitive Data Protection / Dataflow) that fills 'masked'
# from 'raw_prod' runs as this SA inside the data project.
resource "google_service_account" "masking" {
  project      = module.data_project.project_id
  account_id   = "data-masking"
  display_name = "De-identification job for ${var.customer}"
}

resource "google_bigquery_dataset_iam_member" "masking" {
  for_each   = { raw_prod = "roles/bigquery.dataViewer", masked = "roles/bigquery.dataEditor" }
  project    = module.data_project.project_id
  dataset_id = google_bigquery_dataset.zone[each.key].dataset_id
  role       = each.value
  member     = "serviceAccount:${google_service_account.masking.email}"
}

# ---------------- VPC Service Controls perimeter ----------------
module "perimeter" {
  source = "../../modules/vpc-sc-perimeter"

  access_policy_id = data.terraform_remote_state.bootstrap.outputs.access_policy_id
  name             = "tenant_${replace(var.customer, "-", "_")}"
  project_numbers  = concat([for p in module.env_project : p.project_number], [module.data_project.project_number])
  dry_run          = !try(local.tenant.vpc_sc_enforced, false)

  # Pooled GKE workloads reach Google APIs from the env's Shared VPC host network.
  ingress_source_projects = [for env in local.pooled_envs : local.net.host_project_numbers[env]]
  workload_identities     = local.workload_identities
  admin_identities        = [for sa in values(data.terraform_remote_state.bootstrap.outputs.terraform_sa) : "serviceAccount:${sa}"]
}

output "folder_id" { value = google_folder.customer.name }
output "env_projects" {
  value = { for k, p in module.env_project : k => { id = p.project_id, number = p.project_number } }
}
output "data_project_id" { value = module.data_project.project_id }
output "datasets" { value = { for k, d in google_bigquery_dataset.zone : k => d.dataset_id } }
output "buckets" { value = { for k, b in google_storage_bucket.zone : k => b.name } }
