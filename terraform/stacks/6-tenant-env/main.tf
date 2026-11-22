# Per customer x environment (state prefix: tenants/<customer>/<env>).
# Reads config/tenants/<customer>/tenant.yaml and every <env>/<product>.yaml release file:
#   subnet + firewall, product identities, Cloud Run services, MIGs, dedicated GKE (if any),
#   Workload Identity bindings for GKE products, the customer load balancer, and
#   data-sharing IAM between this customer's environments.
variable "customer" { type = string }
variable "env" {
  type = string
  validation {
    condition     = contains(["dev", "stage", "uat", "prod"], var.env)
    error_message = "env must be dev, stage, uat or prod."
  }
}

data "terraform_remote_state" "net" {
  backend = "gcs"
  config  = { bucket = var.state_bucket, prefix = "2-networking" }
}
data "terraform_remote_state" "platform" {
  backend = "gcs"
  config  = { bucket = var.state_bucket, prefix = "3-platform" }
}
data "terraform_remote_state" "fleet" {
  backend = "gcs"
  config  = { bucket = var.state_bucket, prefix = "4-gke-fleet" }
}
data "terraform_remote_state" "base" {
  backend = "gcs"
  config  = { bucket = var.state_bucket, prefix = "tenants/${var.customer}/base" }
}

locals {
  tenant_dir = "${local.config_dir}/tenants/${var.customer}"
  tenant     = yamldecode(file("${local.tenant_dir}/tenant.yaml"))
  catalog    = yamldecode(file("${local.config_dir}/catalog/products.yaml"))
  net        = data.terraform_remote_state.net.outputs
  base       = data.terraform_remote_state.base.outputs
  region     = try(local.tenant.region, local.platform.default_region)

  project_id     = local.base.env_projects[var.env].id
  project_number = local.base.env_projects[var.env].number
  host_project   = local.net.host_projects[var.env]
  labels         = { customer = var.customer, env = var.env }
  network_tag    = "t-${var.customer}"

  # ---- release files: config/tenants/<customer>/<env>/<product>.yaml ----
  releases = {
    for f in fileset("${local.tenant_dir}/${var.env}", "*.yaml") :
    trimsuffix(f, ".yaml") => yamldecode(file("${local.tenant_dir}/${var.env}/${f}"))
  }
  cloudrun = { for k, r in local.releases : k => r if r.runtime == "cloudrun" }
  mig      = { for k, r in local.releases : k => r if r.runtime == "mig" }
  gke      = { for k, r in local.releases : k => r if r.runtime == "gke" }

  gke_cfg   = local.tenant.gke[var.env]
  dedicated = local.gke_cfg.mode == "dedicated" && length(local.gke) > 0
  ded_idx   = try(local.gke_cfg.dedicated_index, 0)

  # ---- IP plan: the same /22 slot of each env supernet for this customer ----
  subnet_cidr = cidrsubnet(local.envs[var.env].tenant_supernet, 10, local.tenant.network.subnet_index)
  secondary = local.dedicated ? tomap({
    pods = cidrsubnet("100.96.0.0/11", 5, local.ded_idx)
    svc  = cidrsubnet("10.240.0.0/12", 8, 16 + local.ded_idx)
  }) : tomap({})

  cloudrun_agent = "serviceAccount:service-${local.project_number}@serverless-robot-prod.iam.gserviceaccount.com"
  gke_agent      = "serviceAccount:service-${local.project_number}@container-engine-robot.iam.gserviceaccount.com"
  cloudservices  = "serviceAccount:${local.project_number}@cloudservices.gserviceaccount.com"

  registry          = data.terraform_remote_state.platform.outputs.container_registry
  artifacts_project = data.terraform_remote_state.platform.outputs.artifacts_project_id
  hostname          = { for k, r in local.releases : k => "${r.product}.${var.customer}.${var.env}.${local.platform.domain}" }

  # Feature flags + config become plain env vars / metadata for non-Helm runtimes.
  app_env = {
    for k, r in local.releases : k => merge(
      { CUSTOMER = var.customer, ENVIRONMENT = var.env, PRODUCT = r.product },
      { for name, v in try(r.config, {}) : name => tostring(v) },
      { for name, v in try(r.featureFlags, {}) : "FF_${upper(name)}" => tostring(v) },
    )
  }
}

# ---------------- Network ----------------
module "subnet" {
  source = "../../modules/tenant-subnet"

  host_project_id  = local.host_project
  network          = local.net.networks[var.env]
  name             = "${var.customer}-${var.env}"
  region           = local.region
  cidr             = local.subnet_cidr
  secondary_ranges = local.secondary
  network_users = compact([
    local.cloudservices,
    length(local.cloudrun) > 0 ? local.cloudrun_agent : "",
    local.dedicated ? local.gke_agent : "",
  ])
}

# Intra-customer traffic only: workloads of this customer accept traffic from this
# customer's subnet. Other customers' subnets fall through to the implicit deny.
resource "google_compute_firewall" "intra_customer" {
  project       = local.host_project
  name          = "allow-intra-${var.customer}-${var.env}"
  network       = local.net.networks[var.env]
  direction     = "INGRESS"
  priority      = 1000
  source_ranges = [local.subnet_cidr]
  target_tags   = [local.network_tag]
  allow {
    protocol = "tcp"
  }
}

resource "google_project_iam_member" "gke_host_agent" {
  count   = local.dedicated ? 1 : 0
  project = local.host_project
  role    = "roles/container.hostServiceAgentUser"
  member  = local.gke_agent
}

# ---------------- Product identities (one GSA per product per customer-env) ----------------
resource "google_service_account" "product" {
  for_each     = local.releases
  project      = local.project_id
  account_id   = "${each.value.product}-sa" # 6-30 chars; KSA name stays <product>
  display_name = "${each.value.product} (${var.customer}/${var.env})"
}

resource "google_project_iam_member" "product" {
  for_each = {
    for pair in setproduct(keys(local.releases), [
      "roles/logging.logWriter", "roles/monitoring.metricWriter", "roles/cloudtrace.agent",
      "roles/secretmanager.secretAccessor", "roles/cloudsql.client",
    ]) : "${pair[0]}/${pair[1]}" => { product = pair[0], role = pair[1] }
  }
  project = local.project_id
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.product[each.value.product].email}"
}

resource "google_artifact_registry_repository_iam_member" "run_pull" {
  count      = length(local.cloudrun) > 0 ? 1 : 0
  project    = local.artifacts_project
  location   = local.region
  repository = "containers"
  role       = "roles/artifactregistry.reader"
  member     = local.cloudrun_agent
}

# ---------------- Cloud Run products ----------------
module "cloudrun" {
  source   = "../../modules/cloud-run-service"
  for_each = local.cloudrun

  project_id      = local.project_id
  region          = local.region
  name            = each.value.product
  image_repo      = "${local.registry}/${each.value.product}"
  version_tag     = each.value.version
  canary          = try(each.value.cloudrun.canary, null)
  service_account = google_service_account.product[each.key].email
  network         = local.net.networks[var.env]
  subnetwork      = module.subnet.self_link
  port            = local.catalog.products[each.value.product].port
  cpu             = try(each.value.cloudrun.cpu, "1")
  memory          = try(each.value.cloudrun.memory, "512Mi")
  min_instances   = try(each.value.cloudrun.minInstances, 0)
  max_instances   = try(each.value.cloudrun.maxInstances, 10)
  env             = local.app_env[each.key]
  labels          = merge(local.labels, { product = each.value.product })

  deletion_protection = var.env == "prod"
  depends_on          = [google_artifact_registry_repository_iam_member.run_pull]
}

# ---------------- MIG products ----------------
module "mig" {
  source   = "../../modules/mig-service"
  for_each = local.mig

  project_id         = local.project_id
  region             = local.region
  name               = each.value.product
  version_tag        = each.value.version
  source_image       = "projects/${local.artifacts_project}/global/images/${each.value.product}-${replace(each.value.version, ".", "-")}"
  machine_type       = try(each.value.mig.machineType, "e2-standard-2")
  min_replicas       = try(each.value.mig.minReplicas, 1)
  max_replicas       = try(each.value.mig.maxReplicas, 3)
  port               = local.catalog.products[each.value.product].port
  health_path        = try(local.catalog.products[each.value.product].health_path, "/healthz")
  subnetwork         = module.subnet.self_link
  subnetwork_project = local.host_project
  service_account    = google_service_account.product[each.key].email
  network_tags       = [local.network_tag]
  metadata           = local.app_env[each.key]
  labels             = merge(local.labels, { product = each.value.product })
}

# ---------------- Customer load balancer (Cloud Run + MIG products) ----------------
module "ingress" {
  source = "../../modules/tenant-ingress"
  count  = length(local.cloudrun) + length(local.mig) > 0 ? 1 : 0

  project_id = local.project_id
  name       = "${var.customer}-${var.env}"
  backends = merge(
    { for k, r in local.cloudrun : k => { host = local.hostname[k], type = "serverless", group = module.cloudrun[k].neg_id } },
    { for k, r in local.mig : k => { host = local.hostname[k], type = "mig", group = module.mig[k].instance_group, health_check = module.mig[k].health_check_id } },
  )
}

# ---------------- GKE: dedicated cluster (optional) + Workload Identity ----------------
module "dedicated_gke" {
  source = "../../modules/gke-cluster"
  count  = local.dedicated ? 1 : 0

  project_id          = local.project_id
  name                = local.gke_cfg.cluster
  region              = local.region
  network             = local.net.networks[var.env]
  subnetwork          = module.subnet.self_link
  pods_range_name     = "pods"
  services_range_name = "svc"
  master_cidr         = cidrsubnet("172.16.0.0/16", 12, 16 + local.ded_idx)
  release_channel     = var.env == "prod" ? "STABLE" : "REGULAR"
  master_authorized_networks = {
    platform-runners = "10.0.240.0/22"
  }
  labels = merge(local.labels, { tier = "dedicated" })
  node_pools = {
    general = { machine_type = "n2-standard-8", min = 3, max = 30 }
  }
  depends_on = [google_project_iam_member.gke_host_agent]
}

resource "google_artifact_registry_repository_iam_member" "dedicated_pull" {
  count      = local.dedicated ? 1 : 0
  project    = local.artifacts_project
  location   = local.region
  repository = "containers"
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${module.dedicated_gke[0].node_service_account}"
}

locals {
  # Pooled: the identity pool of the env's shared GKE project; dedicated: this project's pool.
  workload_pool = local.dedicated ? "${local.project_id}.svc.id.goog" : "${data.terraform_remote_state.fleet.outputs.projects[var.env]}.svc.id.goog"
}

# Namespace = customer, KSA = product (created by the Helm charts).
resource "google_service_account_iam_member" "workload_identity" {
  for_each           = local.gke
  service_account_id = google_service_account.product[each.key].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${local.workload_pool}[${var.customer}/${each.value.product}]"
}

# ---------------- Data sharing between THIS customer's environments ----------------
locals {
  ds          = try(local.tenant.data_sharing, {})
  read_masked = contains(try(local.ds.masked_from_prod_to, []), var.env)
  read_raw    = contains(try(local.ds.raw_from_prod_to, []), var.env)

  dataset_grants = merge(
    { shared_reference = "roles/bigquery.dataViewer" },
    var.env == "prod" ? { raw_prod = "roles/bigquery.dataEditor" } : {},
    local.read_masked ? { masked = "roles/bigquery.dataViewer" } : {},
    local.read_raw && var.env != "prod" ? { raw_prod = "roles/bigquery.dataViewer" } : {},
  )
  bucket_grants = merge(
    { shared_reference = "roles/storage.objectViewer" },
    var.env == "prod" ? { raw_prod = "roles/storage.objectAdmin" } : {},
    local.read_masked ? { masked = "roles/storage.objectViewer" } : {},
    local.read_raw && var.env != "prod" ? { raw_prod = "roles/storage.objectViewer" } : {},
  )
}

resource "google_bigquery_dataset_iam_member" "share" {
  for_each = {
    for pair in setproduct(keys(local.releases), keys(local.dataset_grants)) :
    "${pair[0]}/${pair[1]}" => { product = pair[0], zone = pair[1] }
  }
  project    = local.base.data_project_id
  dataset_id = local.base.datasets[each.value.zone]
  role       = local.dataset_grants[each.value.zone]
  member     = "serviceAccount:${google_service_account.product[each.value.product].email}"
}

resource "google_storage_bucket_iam_member" "share" {
  for_each = {
    for pair in setproduct(keys(local.releases), keys(local.bucket_grants)) :
    "${pair[0]}/${pair[1]}" => { product = pair[0], zone = pair[1] }
  }
  bucket = local.base.buckets[each.value.zone]
  role   = local.bucket_grants[each.value.zone]
  member = "serviceAccount:${google_service_account.product[each.value.product].email}"
}

output "project_id" { value = local.project_id }
output "subnet" { value = local.subnet_cidr }
output "gke_mode" { value = local.gke_cfg.mode }
output "hosts" { value = local.hostname }
output "lb_ip" { value = try(module.ingress[0].ip_address, null) }
output "versions" { value = { for k, r in local.releases : k => r.version } }
