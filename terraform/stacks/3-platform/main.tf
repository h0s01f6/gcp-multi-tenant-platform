# Shared platform services: CI/CD runners (GitHub/Bitbucket), Ansible runners,
# Workload Identity Federation, Artifact Registry, central logging and the
# management cluster that hosts Argo CD.
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
  net        = data.terraform_remote_state.net.outputs
  org        = data.terraform_remote_state.org.outputs
  region     = local.net.region
  cicd       = local.platform.cicd
  infra_repo = "${local.cicd.github_org}/gcp-multi-tenant-platform"

  # A service project can attach to only one Shared VPC host, and prod/non-prod
  # CI must be isolated anyway, so there are two CI projects.
  projects = {
    cicd-nonprod  = { env = "dev", host = "dev" }
    cicd-prod     = { env = "prod", host = "prod" }
    artifacts     = { env = "prod", host = null }
    observability = { env = "prod", host = null }
  }
}

module "project" {
  source   = "../../modules/tenant-project"
  for_each = local.projects

  project_id       = "${local.prefix}-${each.key}"
  folder_id        = local.org.folders["platform"]
  billing_account  = local.platform.billing_account
  env_tag_value_id = local.org.env_tag_values[each.value.env]
  host_project_id  = each.value.host == null ? null : local.net.host_projects[each.value.host]
  labels           = { role = each.key }
  apis = [
    "compute.googleapis.com", "artifactregistry.googleapis.com", "secretmanager.googleapis.com",
    "iam.googleapis.com", "iamcredentials.googleapis.com", "sts.googleapis.com",
    "logging.googleapis.com", "container.googleapis.com", "gkehub.googleapis.com",
  ]
}

# ---------------- Artifact Registry ----------------
resource "google_artifact_registry_repository" "repo" {
  for_each      = { containers = "Product container images", charts = "Helm charts (OCI)" }
  project       = module.project["artifacts"].project_id
  location      = local.region
  repository_id = each.key
  description   = each.value
  format        = "DOCKER"

  docker_config {
    immutable_tags = true # a version tag can never be overwritten
  }

  cleanup_policies {
    id     = "delete-untagged"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "1209600s" # 14 days
    }
  }
}

# ---------------- Workload Identity Federation (no SA keys in CI) ----------------
resource "google_iam_workload_identity_pool" "ci" {
  project                   = module.project["cicd-prod"].project_id
  workload_identity_pool_id = "ci-pool"
  display_name              = "CI pipelines"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = module.project["cicd-prod"].project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.ci.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub Actions"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.repo_env"   = "assertion.repository + ':' + (has(assertion.environment) ? assertion.environment : 'none')"
  }
  attribute_condition = "assertion.repository_owner == '${local.cicd.github_org}'"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_iam_workload_identity_pool_provider" "bitbucket" {
  project                            = module.project["cicd-prod"].project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.ci.workload_identity_pool_id
  workload_identity_pool_provider_id = "bitbucket"
  display_name                       = "Bitbucket Pipelines"
  attribute_mapping = {
    "google.subject"           = "assertion.sub"
    "attribute.workspace_uuid" = "assertion.workspaceUuid"
  }
  attribute_condition = "assertion.workspaceUuid == '${local.cicd.bitbucket_workspace_uuid}'"
  oidc {
    issuer_uri        = "https://api.bitbucket.org/2.0/workspaces/${local.cicd.bitbucket_workspace}/pipelines-config/identity/oidc"
    allowed_audiences = ["ari:cloud:bitbucket::workspace/${trim(local.cicd.bitbucket_workspace_uuid, "{}")}"]
  }
}

locals {
  pool_principal = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.ci.name}"
}

# Any workflow in the infra repo may plan/apply non-prod; only jobs running in the
# protected GitHub "prod" environment (required reviewers) may impersonate tf-prod.
resource "google_service_account_iam_member" "tf_nonprod_wif" {
  service_account_id = "projects/${data.terraform_remote_state.bootstrap.outputs.seed_project_id}/serviceAccounts/${data.terraform_remote_state.bootstrap.outputs.terraform_sa["nonprod"]}"
  role               = "roles/iam.workloadIdentityUser"
  member             = "${local.pool_principal}/attribute.repository/${local.infra_repo}"
}

resource "google_service_account_iam_member" "tf_prod_wif" {
  service_account_id = "projects/${data.terraform_remote_state.bootstrap.outputs.seed_project_id}/serviceAccounts/${data.terraform_remote_state.bootstrap.outputs.terraform_sa["prod"]}"
  role               = "roles/iam.workloadIdentityUser"
  member             = "${local.pool_principal}/attribute.repo_env/${local.infra_repo}:prod"
}

# Product build pipelines push images/charts using WIF directly (principal of the product repos).
resource "google_artifact_registry_repository_iam_member" "ci_push" {
  for_each   = google_artifact_registry_repository.repo
  project    = each.value.project
  location   = each.value.location
  repository = each.value.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "${local.pool_principal}/attribute.repo_env/${local.cicd.github_org}/product-builds:release"
}

# ---------------- Shared runners ----------------
resource "google_secret_manager_secret" "runner_token" {
  for_each  = toset(["cicd-nonprod", "cicd-prod"])
  project   = module.project[each.key].project_id
  secret_id = "runner-registration-token"
  replication {
    auto {}
  }
}

locals {
  runner_pools = {
    gh-runner-nonprod = { project = "cicd-nonprod", host = "dev", script = "github-runner.sh", min = 1, max = 10 }
    gh-runner-prod    = { project = "cicd-prod", host = "prod", script = "github-runner.sh", min = 1, max = 5 }
    ansible-nonprod   = { project = "cicd-nonprod", host = "dev", script = "ansible-runner.sh", min = 1, max = 3 }
    ansible-prod      = { project = "cicd-prod", host = "prod", script = "ansible-runner.sh", min = 1, max = 3 }
  }
}

module "runners" {
  source   = "../../modules/runner-pool"
  for_each = local.runner_pools

  project_id             = module.project[each.value.project].project_id
  region                 = local.region
  name                   = each.key
  subnetwork             = local.net.platform_subnets[each.value.host]
  subnetwork_project     = local.net.host_projects[each.value.host]
  startup_script         = file("${path.module}/scripts/${each.value.script}")
  registration_secret_id = startswith(each.key, "gh-") ? google_secret_manager_secret.runner_token[each.value.project].secret_id : null
  min_replicas           = each.value.min
  max_replicas           = each.value.max
  labels                 = { role = "ci-runner" }
}

resource "google_compute_subnetwork_iam_member" "runner_subnet" {
  for_each   = toset(["cicd-nonprod", "cicd-prod"])
  project    = local.net.host_projects[local.projects[each.key].host]
  region     = local.region
  subnetwork = "platform-${local.projects[each.key].host}"
  role       = "roles/compute.networkUser"
  member     = "serviceAccount:${module.project[each.key].project_number}@cloudservices.gserviceaccount.com"
}

# Ansible runners reach VMs only through IAP and OS Login.
resource "google_organization_iam_member" "ansible" {
  for_each = {
    for pair in setproduct(["ansible-nonprod", "ansible-prod"], ["roles/iap.tunnelResourceAccessor", "roles/compute.osAdminLogin", "roles/compute.viewer"]) :
    "${pair[0]}/${pair[1]}" => { pool = pair[0], role = pair[1] }
  }
  org_id = local.platform.org_id
  role   = each.value.role
  member = "serviceAccount:${module.runners[each.value.pool].service_account_email}"
}

# ---------------- Management cluster (Argo CD) ----------------
# Uses the reserved shard 7 ranges of the prod pool subnet. Argo CD reaches tenant
# clusters through GKE Fleet Connect Gateway, so no network peering is required.
resource "google_project_iam_member" "mgmt_host_agent" {
  project = local.net.host_projects["prod"]
  role    = "roles/container.hostServiceAgentUser"
  member  = "serviceAccount:service-${module.project["cicd-prod"].project_number}@container-engine-robot.iam.gserviceaccount.com"
}

resource "google_compute_subnetwork_iam_member" "mgmt_subnet" {
  for_each = {
    gke           = "serviceAccount:service-${module.project["cicd-prod"].project_number}@container-engine-robot.iam.gserviceaccount.com"
    cloudservices = "serviceAccount:${module.project["cicd-prod"].project_number}@cloudservices.gserviceaccount.com"
  }
  project    = local.net.host_projects["prod"]
  region     = local.region
  subnetwork = local.net.gke_pool_subnet_names["prod"]
  role       = "roles/compute.networkUser"
  member     = each.value
}

module "mgmt_cluster" {
  source = "../../modules/gke-cluster"

  project_id          = module.project["cicd-prod"].project_id
  name                = "mgmt-argocd"
  region              = local.region
  network             = local.net.networks["prod"]
  subnetwork          = local.net.gke_pool_subnets["prod"]
  pods_range_name     = "pods-7"
  services_range_name = "svc-7"
  master_cidr         = cidrsubnet("172.16.0.0/16", 12, 15)
  release_channel     = "STABLE"
  labels              = { role = "management" }
  node_pools = {
    system = { machine_type = "e2-standard-4", min = 1, max = 3 }
  }
  depends_on = [google_project_iam_member.mgmt_host_agent, google_compute_subnetwork_iam_member.mgmt_subnet]
}

# ---------------- Central logging ----------------
resource "google_logging_project_bucket_config" "audit" {
  project        = module.project["observability"].project_id
  location       = local.region
  bucket_id      = "org-audit"
  retention_days = 400
}

resource "google_logging_organization_sink" "audit" {
  name             = "org-audit-to-observability"
  org_id           = local.platform.org_id
  destination      = "logging.googleapis.com/${google_logging_project_bucket_config.audit.id}"
  include_children = true
  filter           = "logName:\"cloudaudit.googleapis.com\""
}

resource "google_project_iam_member" "audit_sink_writer" {
  project = module.project["observability"].project_id
  role    = "roles/logging.bucketWriter"
  member  = google_logging_organization_sink.audit.writer_identity
}

output "projects" { value = { for k, p in module.project : k => p.project_id } }
output "artifacts_project_id" { value = module.project["artifacts"].project_id }
output "container_registry" {
  value = "${local.region}-docker.pkg.dev/${module.project["artifacts"].project_id}/containers"
}
output "wif_provider_github" { value = google_iam_workload_identity_pool_provider.github.name }
output "wif_provider_bitbucket" { value = google_iam_workload_identity_pool_provider.bitbucket.name }
