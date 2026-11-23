# One GKE Autopilot cell (ADR-008): private nodes, DNS-based control-plane endpoint only, named secondary ranges
# from the IP plan (N1), Dataplane V2 (NetworkPolicy, D8), Gateway API, Binary Authorization (D9, T-S4).
resource "google_container_cluster" "this" {
  project             = var.project
  name                = var.cell.cluster
  location            = var.region
  enable_autopilot    = true
  network             = "projects/${var.host_project}/global/networks/${var.cell.network}"
  subnetwork          = "projects/${var.host_project}/regions/${var.region}/subnetworks/${var.cell.subnet}"
  deletion_protection = true

  ip_allocation_policy {
    cluster_secondary_range_name  = var.cell.pods_range
    services_secondary_range_name = var.cell.services_range
  }

  private_cluster_config {
    enable_private_nodes    = var.cell.private_nodes
    enable_private_endpoint = !var.cell.control_plane.ip_endpoint_external_access # IP endpoint not reachable externally
  }

  control_plane_endpoints_config {
    dns_endpoint_config {
      allow_external_traffic = var.cell.control_plane.dns_endpoint
    }
    ip_endpoints_config {
      enabled = !var.disable_ip_endpoint
    }
  }

  master_authorized_networks_config {}

  gateway_api_config {
    channel = var.cell.gateway_api
  }

  binary_authorization {
    evaluation_mode = "PROJECT_SINGLETON_POLICY_ENFORCE"
  }

  release_channel {
    channel = var.release_channel
  }

  # Stage 8: GKE cost allocation – namespace labels (tenant, product, env) appear in the billing export
  cost_management_config {
    enabled = true
  }

  resource_labels = { env = var.env, env_tier = var.cell.tier, cell = var.cell.cluster }
}
