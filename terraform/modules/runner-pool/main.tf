# Shared, autoscaled pool of CI runners (GitHub Actions / Bitbucket) or Ansible runners.
# Private VMs only; registration tokens are read from Secret Manager at boot.
resource "google_service_account" "this" {
  project      = var.project_id
  account_id   = var.name
  display_name = "Runner pool ${var.name}"
}

resource "google_secret_manager_secret_iam_member" "token" {
  count     = var.registration_secret_id == null ? 0 : 1
  project   = var.project_id
  secret_id = var.registration_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.this.email}"
}

resource "google_compute_instance_template" "this" {
  project      = var.project_id
  name_prefix  = "${var.name}-"
  machine_type = var.machine_type
  tags         = ["iap-ssh", "runner"]
  labels       = merge(var.labels, { pool = var.name })

  disk {
    source_image = var.source_image
    boot         = true
    auto_delete  = true
    disk_size_gb = 100
  }

  network_interface {
    subnetwork         = var.subnetwork
    subnetwork_project = var.subnetwork_project
  }

  service_account {
    email  = google_service_account.this.email
    scopes = ["cloud-platform"]
  }

  shielded_instance_config {
    enable_secure_boot = true
  }

  metadata = {
    enable-oslogin = "TRUE"
    startup-script = var.startup_script
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_compute_region_instance_group_manager" "this" {
  project            = var.project_id
  name               = var.name
  region             = var.region
  base_instance_name = var.name

  version {
    instance_template = google_compute_instance_template.this.self_link_unique
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
    cooldown_period = 180
    cpu_utilization {
      target = 0.7
    }
  }
}
