# Pooled, multi-customer GKE clusters: one project per environment, N shards per env.
data "terraform_remote_state" "org" {
  backend = "gcs"
  config  = { bucket = var.state_bucket, prefix = "1-org" }
}
data "terraform_remote_state" "platform" {
  backend = "gcs"
  config  = { bucket = var.state_bucket, prefix = "3-platform" }
}
data "terraform_remote_state" "net" {
  backend = "gcs"
  config  = { bucket = var.state_bucket, prefix = "2-networking" }
}

locals {
  net    = data.terraform_remote_state.net.outputs
  region = local.net.region
  clusters = merge([
    for env, pools in local.platform.gke_pools : {
      for p in pools : p.name => { env = env, shard = p.shard }
    }
  ]...)
}

module "project" {
  source   = "../../modules/tenant-project"
  for_each = local.envs

  project_id       = "${local.prefix}-gke-${each.key}"
  folder_id        = data.terraform_remote_state.org.outputs.folders["compute"]
  billing_account  = local.platform.billing_account
  env_tag_value_id = data.terraform_remote_state.org.outputs.env_tag_values[each.key]
  host_project_id  = local.net.host_projects[each.key]
  labels           = { env = each.key, role = "gke-pooled" }
  apis = [
    "container.googleapis.com", "compute.googleapis.com", "gkehub.googleapis.com",
    "binaryauthorization.googleapis.com", "logging.googleapis.com", "monitoring.googleapis.com",
  ]
}

# GKE in a Shared VPC service project needs these grants on the host.
resource "google_project_iam_member" "host_agent" {
  for_each = local.envs
  project  = local.net.host_projects[each.key]
  role     = "roles/container.hostServiceAgentUser"
  member   = "serviceAccount:service-${module.project[each.key].project_number}@container-engine-robot.iam.gserviceaccount.com"
}

resource "google_compute_subnetwork_iam_member" "pool_users" {
  for_each = {
    for pair in setproduct(keys(local.envs), ["gke", "cloudservices"]) : "${pair[0]}/${pair[1]}" => { env = pair[0], who = pair[1] }
  }
  project    = local.net.host_projects[each.value.env]
  region     = local.region
  subnetwork = local.net.gke_pool_subnet_names[each.value.env]
  role       = "roles/compute.networkUser"
  member = each.value.who == "gke" ? (
    "serviceAccount:service-${module.project[each.value.env].project_number}@container-engine-robot.iam.gserviceaccount.com"
    ) : (
    "serviceAccount:${module.project[each.value.env].project_number}@cloudservices.gserviceaccount.com"
  )
}

module "cluster" {
  source   = "../../modules/gke-cluster"
  for_each = local.clusters

  project_id          = module.project[each.value.env].project_id
  name                = each.key
  region              = local.region
  network             = local.net.networks[each.value.env]
  subnetwork          = local.net.gke_pool_subnets[each.value.env]
  pods_range_name     = "pods-${each.value.shard}"
  services_range_name = "svc-${each.value.shard}"
  master_cidr         = cidrsubnet("172.16.0.0/16", 12, each.value.shard)
  release_channel     = each.value.env == "prod" ? "STABLE" : "REGULAR"
  master_authorized_networks = {
    platform-runners = "10.0.240.0/22"
  }
  labels = { env = each.value.env, tier = "pooled" }

  node_pools = {
    general = {
      machine_type = each.value.env == "prod" ? "n2-standard-8" : "e2-standard-4"
      min          = each.value.env == "prod" ? 3 : 1
      max          = each.value.env == "prod" ? 60 : 15
      spot         = contains(["dev", "stage"], each.value.env)
    }
  }

  depends_on = [google_project_iam_member.host_agent, google_compute_subnetwork_iam_member.pool_users]
}

# Pooled node pools pull every customer's images (images are not customer-secret;
# customer data access is governed by Workload Identity, not by the node identity).
resource "google_artifact_registry_repository_iam_member" "node_pull" {
  for_each   = module.cluster
  project    = data.terraform_remote_state.platform.outputs.artifacts_project_id
  location   = local.region
  repository = "containers"
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${each.value.node_service_account}"
}

output "projects" { value = { for k, p in module.project : k => p.project_id } }
output "project_numbers" { value = { for k, p in module.project : k => p.project_number } }
output "clusters" {
  value = { for k, c in module.cluster : k => { env = local.clusters[k].env, workload_pool = c.workload_pool } }
}
