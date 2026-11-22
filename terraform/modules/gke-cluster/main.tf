# Private, regional GKE Standard cluster used both for pooled (multi-customer)
# and dedicated (single-customer) tiers.
resource "google_service_account" "nodes" {
  project      = var.project_id
  account_id   = substr("${var.name}-nodes", 0, 30)
  display_name = "GKE nodes for ${var.name}"
}

resource "google_project_iam_member" "nodes" {
  for_each = toset([
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/monitoring.viewer",
    "roles/stackdriver.resourceMetadata.writer",
    "roles/autoscaling.metricsWriter",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.nodes.email}"
}

resource "google_container_cluster" "this" {
  project  = var.project_id
  name     = var.name
  location = var.region

  network         = var.network
  subnetwork      = var.subnetwork
  networking_mode = "VPC_NATIVE"
  ip_allocation_policy {
    cluster_secondary_range_name  = var.pods_range_name
    services_secondary_range_name = var.services_range_name
  }

  remove_default_node_pool = true
  initial_node_count       = 1
  deletion_protection      = var.deletion_protection

  datapath_provider = "ADVANCED_DATAPATH" # Dataplane V2: NetworkPolicy enforcement

  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
    master_ipv4_cidr_block  = var.master_cidr
  }

  master_authorized_networks_config {
    dynamic "cidr_blocks" {
      for_each = var.master_authorized_networks
      content {
        cidr_block   = cidr_blocks.value
        display_name = cidr_blocks.key
      }
    }
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  release_channel {
    channel = var.release_channel
  }

  gateway_api_config {
    channel = "CHANNEL_STANDARD"
  }

  binary_authorization {
    evaluation_mode = "PROJECT_SINGLETON_POLICY_ENFORCE"
  }

  maintenance_policy {
    recurring_window {
      start_time = "2026-01-01T20:30:00Z" # 02:00 IST
      end_time   = "2026-01-02T00:30:00Z"
      recurrence = var.maintenance_recurrence
    }
  }

  resource_labels = var.labels
}

resource "google_container_node_pool" "pools" {
  for_each = var.node_pools

  project  = var.project_id
  cluster  = google_container_cluster.this.name
  location = var.region
  name     = each.key

  autoscaling {
    total_min_node_count = each.value.min
    total_max_node_count = each.value.max
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  node_config {
    machine_type    = each.value.machine_type
    spot            = try(each.value.spot, false)
    service_account = google_service_account.nodes.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    labels          = merge(var.labels, try(each.value.labels, {}))

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }

    # Dedicated pools for a specific customer are tainted so only that customer's pods land there.
    dynamic "taint" {
      for_each = try(each.value.taints, [])
      content {
        key    = taint.value.key
        value  = taint.value.value
        effect = "NO_SCHEDULE"
      }
    }
  }
}
