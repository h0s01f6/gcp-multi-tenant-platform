# One product on Cloud Run inside a customer-env project.
# Revisions are named after the version so traffic can be split between a
# stable version and a canary version (customer-by-customer rollout).
locals {
  stable_revision = "${var.name}-${replace(var.version_tag, ".", "-")}"
  canary_revision = var.canary == null ? null : "${var.name}-${replace(var.canary.version, ".", "-")}"
  # The template always describes the newest revision (canary if set).
  deploy_version  = var.canary == null ? var.version_tag : var.canary.version
  deploy_revision = var.canary == null ? local.stable_revision : local.canary_revision
}

resource "google_cloud_run_v2_service" "this" {
  project             = var.project_id
  name                = var.name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  deletion_protection = var.deletion_protection
  labels              = merge(var.labels, { version = replace(var.version_tag, ".", "_") })

  # Ingress is restricted to the customer's load balancer, so the IAM invoker check is
  # disabled instead of granting allUsers (which domain-restricted sharing would block).
  # Authentication happens at the LB (IAP) or in the application.
  invoker_iam_disabled = var.allow_lb_unauthenticated

  template {
    revision        = substr(lower(replace(local.deploy_revision, "_", "-")), 0, 63)
    service_account = var.service_account
    labels          = merge(var.labels, { version = replace(local.deploy_version, ".", "_") })

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {
        network    = var.network
        subnetwork = var.subnetwork
      }
    }

    containers {
      image = "${var.image_repo}:${local.deploy_version}"

      ports {
        container_port = var.port
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }

      dynamic "env" {
        for_each = var.env
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  dynamic "traffic" {
    for_each = var.canary == null ? [] : [1]
    content {
      type     = "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION"
      revision = local.stable_revision
      percent  = 100 - var.canary.percent
    }
  }

  dynamic "traffic" {
    for_each = var.canary == null ? [] : [1]
    content {
      type     = "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION"
      revision = local.canary_revision
      percent  = var.canary.percent
      tag      = "canary"
    }
  }

  dynamic "traffic" {
    for_each = var.canary == null ? [1] : []
    content {
      type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
      percent = 100
    }
  }
}

# Serverless NEG so the customer's load balancer can route to this service.
resource "google_compute_region_network_endpoint_group" "neg" {
  project               = var.project_id
  name                  = "${var.name}-neg"
  region                = var.region
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = google_cloud_run_v2_service.this.name
  }
}
