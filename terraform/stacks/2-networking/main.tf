# One Shared VPC host project per environment. Customer subnets are added later by
# 6-tenant-env; this stack owns the VPC, pooled-GKE/platform subnets, NAT, PSA and base firewall.
data "terraform_remote_state" "org" {
  backend = "gcs"
  config  = { bucket = var.state_bucket, prefix = "1-org" }
}

locals {
  region      = local.platform.default_region
  pool_shards = range(8) # 0..6 pooled clusters, 7 reserved for platform (mgmt cluster, prod)
}

resource "google_project" "host" {
  for_each            = local.envs
  project_id          = "${local.prefix}-net-${each.key}"
  name                = "${local.prefix}-net-${each.key}"
  folder_id           = data.terraform_remote_state.org.outputs.folders["network"]
  billing_account     = local.platform.billing_account
  auto_create_network = false
  labels              = { env = each.key, role = "network-host" }
}

resource "google_project_service" "host" {
  for_each = {
    for pair in setproduct(keys(local.envs), ["compute.googleapis.com", "servicenetworking.googleapis.com", "dns.googleapis.com", "container.googleapis.com"]) :
    "${pair[0]}/${pair[1]}" => { env = pair[0], api = pair[1] }
  }
  project            = google_project.host[each.value.env].project_id
  service            = each.value.api
  disable_on_destroy = false
}

resource "google_tags_tag_binding" "env" {
  for_each  = local.envs
  parent    = "//cloudresourcemanager.googleapis.com/projects/${google_project.host[each.key].number}"
  tag_value = data.terraform_remote_state.org.outputs.env_tag_values[each.key]
}

resource "google_compute_shared_vpc_host_project" "host" {
  for_each   = local.envs
  project    = google_project.host[each.key].project_id
  depends_on = [google_project_service.host]
}

resource "google_compute_network" "vpc" {
  for_each                = local.envs
  project                 = google_project.host[each.key].project_id
  name                    = "vpc-${each.key}"
  auto_create_subnetworks = false
  routing_mode            = "GLOBAL"
  depends_on              = [google_project_service.host]
}

# Subnet for pooled GKE clusters, with secondary ranges pre-allocated per shard.
resource "google_compute_subnetwork" "gke_pool" {
  for_each                 = local.envs
  project                  = google_project.host[each.key].project_id
  name                     = "gke-pool-${each.key}"
  region                   = local.region
  network                  = google_compute_network.vpc[each.key].id
  ip_cidr_range            = each.value.gke_pool_subnet
  private_ip_google_access = true

  dynamic "secondary_ip_range" {
    for_each = local.pool_shards
    content {
      range_name    = "pods-${secondary_ip_range.value}"
      ip_cidr_range = cidrsubnet("100.64.0.0/11", 3, secondary_ip_range.value)
    }
  }
  dynamic "secondary_ip_range" {
    for_each = local.pool_shards
    content {
      range_name    = "svc-${secondary_ip_range.value}"
      ip_cidr_range = cidrsubnet("10.240.0.0/12", 8, secondary_ip_range.value)
    }
  }
}

# Platform subnet: CI runners, Ansible runners, management cluster nodes.
resource "google_compute_subnetwork" "platform" {
  for_each                 = local.envs
  project                  = google_project.host[each.key].project_id
  name                     = "platform-${each.key}"
  region                   = local.region
  network                  = google_compute_network.vpc[each.key].id
  ip_cidr_range            = "10.0.240.0/22"
  private_ip_google_access = true
}

resource "google_compute_router" "this" {
  for_each = local.envs
  project  = google_project.host[each.key].project_id
  name     = "rtr-${each.key}"
  region   = local.region
  network  = google_compute_network.vpc[each.key].id
}

resource "google_compute_router_nat" "this" {
  for_each                           = local.envs
  project                            = google_project.host[each.key].project_id
  name                               = "nat-${each.key}"
  router                             = google_compute_router.this[each.key].name
  region                             = local.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# Private Service Access for Cloud SQL / Memorystore private IPs.
resource "google_compute_global_address" "psa" {
  for_each      = local.envs
  project       = google_project.host[each.key].project_id
  name          = "psa-${each.key}"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  address       = "10.1.0.0"
  prefix_length = 16
  network       = google_compute_network.vpc[each.key].id
}

resource "google_service_networking_connection" "psa" {
  for_each                = local.envs
  network                 = google_compute_network.vpc[each.key].id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.psa[each.key].name]
}

# ---- Baseline firewall. Ingress is implicitly denied; customers get intra-tenant
# allow rules from 6-tenant-env, so customers can never reach each other. ----
resource "google_compute_firewall" "lb_health_checks" {
  for_each      = local.envs
  project       = google_project.host[each.key].project_id
  name          = "allow-google-lb-hc"
  network       = google_compute_network.vpc[each.key].id
  direction     = "INGRESS"
  source_ranges = ["35.191.0.0/16", "130.211.0.0/22"]
  target_tags   = ["lb-backend"]
  allow {
    protocol = "tcp"
    ports    = ["80", "443", "8080"]
  }
}

resource "google_compute_firewall" "iap_ssh" {
  for_each      = local.envs
  project       = google_project.host[each.key].project_id
  name          = "allow-iap-ssh"
  network       = google_compute_network.vpc[each.key].id
  direction     = "INGRESS"
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["iap-ssh"]
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

output "host_projects" { value = { for k, p in google_project.host : k => p.project_id } }
output "host_project_numbers" { value = { for k, p in google_project.host : k => p.number } }
output "networks" { value = { for k, n in google_compute_network.vpc : k => n.self_link } }
output "gke_pool_subnets" { value = { for k, s in google_compute_subnetwork.gke_pool : k => s.self_link } }
output "gke_pool_subnet_names" { value = { for k, s in google_compute_subnetwork.gke_pool : k => s.name } }
output "platform_subnets" { value = { for k, s in google_compute_subnetwork.platform : k => s.self_link } }
output "region" { value = local.region }
