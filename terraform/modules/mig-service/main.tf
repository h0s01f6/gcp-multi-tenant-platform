# A VM-based product: golden image per version -> instance template -> regional MIG.
# Changing the version creates a new template and the MIG rolls it out proactively.
resource "google_compute_instance_template" "this" {
  project      = var.project_id
  name_prefix  = "${var.name}-${replace(var.version_tag, ".", "-")}-"
  machine_type = var.machine_type
  region       = var.region
  tags         = concat(["lb-backend", "iap-ssh"], var.network_tags)
  labels       = merge(var.labels, { version = replace(var.version_tag, ".", "_") })

  disk {
    source_image = var.source_image
    boot         = true
    auto_delete  = true
    disk_size_gb = var.disk_size_gb
    disk_type    = "pd-balanced"
  }

  network_interface {
    subnetwork         = var.subnetwork
    subnetwork_project = var.subnetwork_project
    # no access_config => no external IP (also enforced by org policy)
  }

  service_account {
    email  = var.service_account
    scopes = ["cloud-platform"]
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  # Customer/env-specific configuration is injected at boot; secrets are read from
  # Secret Manager by the startup agent using the attached service account.
  metadata = merge(var.metadata, {
    enable-oslogin = "TRUE"
    product        = var.name
    version        = var.version_tag
  })

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_compute_health_check" "this" {
  project             = var.project_id
  name                = "${var.name}-hc"
  check_interval_sec  = 10
  timeout_sec         = 5
  healthy_threshold   = 2
  unhealthy_threshold = 3

  http_health_check {
    port         = var.port
    request_path = var.health_path
  }
}

resource "google_compute_region_instance_group_manager" "this" {
  project            = var.project_id
  name               = "${var.name}-mig"
  region             = var.region
  base_instance_name = var.name

  version {
    name              = var.version_tag
    instance_template = google_compute_instance_template.this.self_link_unique
  }

  named_port {
    name = "http"
    port = var.port
  }

  auto_healing_policies {
    health_check      = google_compute_health_check.this.id
    initial_delay_sec = 300
  }

  update_policy {
    type                  = "PROACTIVE"
    minimal_action        = "REPLACE"
    max_surge_fixed       = 3 # >= number of zones for regional MIGs
    max_unavailable_fixed = 0
    replacement_method    = "SUBSTITUTE"
  }
}

resource "google_compute_region_autoscaler" "this" {
  project = var.project_id
  name    = "${var.name}-as"
  region  = var.region
  target  = google_compute_region_instance_group_manager.this.id

  autoscaling_policy {
    min_replicas    = var.min_replicas
    max_replicas    = var.max_replicas
    cooldown_period = 120

    cpu_utilization {
      target = 0.6
    }
  }
}
