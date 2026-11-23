# Organisation stack (tf-org): folders, guardrails, identity plumbing and shared projects. Inputs are generated
# (build/tfvars/org/org.auto.tfvars.json); see terraform/stacks.yaml for ownership.
provider "google" {
  billing_project       = "bootstrap-seed"
  user_project_override = true
}

module "folders" {
  source  = "../../modules/folders"
  org_id  = var.org_id
  folders = var.folders
}

module "org_policies" {
  source     = "../../modules/org-policies"
  org_id     = var.org_id
  folder_ids = module.folders.ids
  policies   = var.org_policies
}

module "hierarchical_firewall" {
  source     = "../../modules/firewall-hierarchical"
  org_id     = var.org_id
  folder_ids = module.folders.ids
  policies   = var.hierarchical_firewall_policies
}

# Shared and host projects (fixed set; platform and tenant projects come from tier stacks)
module "shared_projects" {
  source          = "../../modules/project"
  for_each        = toset(var.shared_projects)
  name            = each.key
  folder_id       = module.folders.ids["fldr-shared"]
  billing_account = var.billing_account
  labels          = { env_tier = "shared" }
  apis = ["iam.googleapis.com", "cloudkms.googleapis.com", "artifactregistry.googleapis.com", "containeranalysis.googleapis.com",
  "binaryauthorization.googleapis.com", "logging.googleapis.com", "monitoring.googleapis.com", "run.googleapis.com"]
}

module "host_projects" {
  source          = "../../modules/project"
  for_each        = toset(var.host_projects)
  name            = each.key
  folder_id       = module.folders.ids["fldr-network"]
  billing_account = var.billing_account
  labels          = { env_tier = trimprefix(each.key, "net-host-") }
  apis            = ["compute.googleapis.com", "servicenetworking.googleapis.com", "dns.googleapis.com", "container.googleapis.com"]
}

resource "google_compute_shared_vpc_host_project" "this" {
  for_each = module.host_projects
  project  = each.value.project_id
}

resource "google_artifact_registry_repository" "this" {
  for_each      = toset(var.artifact_repositories)
  project       = module.shared_projects["shr-artifacts"].project_id
  location      = var.region
  repository_id = each.key
  format        = "DOCKER"
  docker_config {
    immutable_tags = each.key == "release" # a released version tag can never point to another digest
  }
}

resource "google_kms_key_ring" "this" {
  for_each   = { for k in var.kms_keyrings : "${k.project}/${k.name}" => k }
  project    = each.value.project
  name       = each.value.name
  location   = var.region
  depends_on = [module.shared_projects]
}

module "attestor" {
  source     = "../../modules/binauthz-attestor"
  attestor   = var.attestor
  region     = var.region
  depends_on = [google_kms_key_ring.this]
}

module "groups" {
  source       = "../../modules/groups"
  customer_id  = var.customer_id
  group_domain = var.group_domain
  groups       = var.groups
  memberships = concat(
    [for m in var.group_managers : merge(m, { manager = true })],
    var.pipeline_memberships
  )
}

module "iam" {
  source          = "../../modules/iam-bindings"
  org_id          = var.org_id
  billing_account = var.billing_account
  folder_ids      = module.folders.ids
  bindings        = var.iam_bindings
  depends_on      = [module.groups, module.shared_projects, module.host_projects, google_artifact_registry_repository.this, google_kms_key_ring.this]
}

module "pam" {
  source       = "../../modules/pam"
  org_id       = var.org_id
  folder_ids   = { for k, v in module.folders.ids : "folder:${replace(trimprefix(k, "fldr-"), "/", "-")}" => v }
  entitlements = var.pam_entitlements
}

module "wif" {
  source           = "../../modules/wif"
  pool             = var.wif.pool
  providers_config = var.wif.providers
  repository_ids   = { for k, v in var.wif.repository_ids : k => lookup(var.repository_ids, k, v) }
  bindings         = var.wif.bindings
  github_org_id    = var.github_org_id
  github_org       = var.github_org
}

module "audit" {
  source     = "../../modules/audit-monitoring"
  org_id     = var.org_id
  folder_ids = module.folders.ids
  audit      = var.audit
  depends_on = [module.shared_projects]
}
