# Tier platform stack (tf-<tier>): shared runtimes. Input: build/tfvars/platform/<tier>.
provider "google" {}

data "terraform_remote_state" "org" {
  backend = "gcs"
  config = {
    bucket = var.org_state_bucket
    prefix = "org"
  }
}

module "projects" {
  source          = "../../modules/project"
  for_each        = { for p in var.projects : p.name => p }
  name            = each.key
  folder_id       = data.terraform_remote_state.org.outputs.folder_ids[each.value.folder]
  billing_account = var.billing_account
  labels          = { env_tier = var.tier }
  host_project    = var.host_project
  apis = ["compute.googleapis.com", "container.googleapis.com", "sqladmin.googleapis.com", "run.googleapis.com",
  "binaryauthorization.googleapis.com", "certificatemanager.googleapis.com", "servicenetworking.googleapis.com"]
}

module "pool_keys" {
  source           = "../../modules/kms"
  keys             = var.pool_keys
  create_key_rings = false # rings created by the org stack in shr-security
}

module "gke_cells" {
  source       = "../../modules/gke-cell"
  for_each     = { for c in var.gke_cells : c.cluster => c }
  project      = each.value.project
  host_project = var.host_project
  region       = var.region
  env          = split("-", each.key)[1]
  cell         = each.value
  depends_on   = [module.projects]
}

module "sql_pools" {
  source       = "../../modules/sql-pool"
  for_each     = { for p in var.sql_pools : p.pool => p }
  pool         = each.value
  region       = var.region
  host_project = var.host_project
  dba_groups   = [for d in var.dba_group_users : d.group_email if d.pool == each.key]
  dr           = try(each.value.dr, null)
  depends_on   = [module.projects, module.pool_keys]
}

module "jobs" {
  source          = "../../modules/cloud-run-job"
  for_each        = { for j in var.jobs : "${j.project}/${j.job}" => j }
  job             = each.value
  region          = var.region
  host_project    = var.host_project
  image           = var.job_image
  service_account = each.value.job == "db-bootstrap" ? "sqlboot-${var.tier}@${each.value.project}.iam.gserviceaccount.com" : "isotest-${var.tier}@shr-cicd-${var.tier}.iam.gserviceaccount.com"
  depends_on      = [module.projects]
}

resource "google_service_account" "sqlboot" {
  for_each   = toset([for p in var.projects : p.name if startswith(p.name, "plt-sql-")])
  project    = each.key
  account_id = "sqlboot-${var.tier}"
  depends_on = [module.projects]
}

resource "google_binary_authorization_policy" "this" {
  for_each                      = { for p in var.binauthz_policies : p.project => p }
  project                       = each.key
  global_policy_evaluation_mode = each.value.global_policy_evaluation_mode
  default_admission_rule {
    evaluation_mode         = each.value.default_admission_rule.evaluation_mode
    enforcement_mode        = each.value.default_admission_rule.enforcement_mode
    require_attestations_by = each.value.default_admission_rule.require_attestations_by
  }
  depends_on = [module.projects]
}

resource "google_binary_authorization_attestor_iam_member" "verifier" {
  for_each = { for p in var.binauthz_policies : p.project => p }
  project  = "shr-build"
  attestor = "built-by-shr-build"
  role     = each.value.verifier.role
  member   = "serviceAccount:${format(each.value.verifier.format, module.projects[each.key].number)}"
}
