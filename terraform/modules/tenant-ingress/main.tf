# One global external Application Load Balancer per customer-env, fronting all of
# that customer's Cloud Run and MIG products with host-based routing and Cloud Armor.
resource "google_compute_security_policy" "this" {
  project = var.project_id
  name    = "${var.name}-armor"

  rule {
    action   = "deny(403)"
    priority = 1000
    match {
      expr {
        expression = "evaluatePreconfiguredWaf('sqli-v33-stable') || evaluatePreconfiguredWaf('xss-v33-stable')"
      }
    }
    description = "OWASP SQLi / XSS"
  }

  rule {
    action   = "allow"
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "default allow"
  }
}

resource "google_compute_backend_service" "this" {
  for_each = var.backends

  project               = var.project_id
  name                  = "${var.name}-${each.key}"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTP"
  port_name             = each.value.type == "mig" ? "http" : null
  timeout_sec           = each.value.type == "mig" ? 30 : null
  health_checks         = each.value.type == "mig" ? [each.value.health_check] : null
  security_policy       = google_compute_security_policy.this.id

  backend {
    group           = each.value.group
    balancing_mode  = each.value.type == "mig" ? "UTILIZATION" : null
    capacity_scaler = each.value.type == "mig" ? 1.0 : null
  }

  log_config {
    enable      = true
    sample_rate = 0.2
  }
}

resource "google_compute_url_map" "this" {
  project         = var.project_id
  name            = "${var.name}-urlmap"
  default_service = google_compute_backend_service.this[keys(var.backends)[0]].id

  dynamic "host_rule" {
    for_each = var.backends
    content {
      hosts        = [host_rule.value.host]
      path_matcher = host_rule.key
    }
  }

  dynamic "path_matcher" {
    for_each = var.backends
    content {
      name            = path_matcher.key
      default_service = google_compute_backend_service.this[path_matcher.key].id
    }
  }
}

resource "google_compute_managed_ssl_certificate" "this" {
  project = var.project_id
  name    = "${var.name}-cert"
  managed {
    domains = [for b in var.backends : b.host]
  }
}

resource "google_compute_target_https_proxy" "this" {
  project          = var.project_id
  name             = "${var.name}-https"
  url_map          = google_compute_url_map.this.id
  ssl_certificates = [google_compute_managed_ssl_certificate.this.id]
}

resource "google_compute_global_address" "this" {
  project = var.project_id
  name    = "${var.name}-ip"
}

resource "google_compute_global_forwarding_rule" "this" {
  project               = var.project_id
  name                  = "${var.name}-https"
  target                = google_compute_target_https_proxy.this.id
  ip_address            = google_compute_global_address.this.address
  port_range            = "443"
  load_balancing_scheme = "EXTERNAL_MANAGED"
}
