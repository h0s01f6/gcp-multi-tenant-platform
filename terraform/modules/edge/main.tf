# Tier front doors (N4): Cloud Armor, wildcard certificates, one global external ALB per product per environment
# for Cloud Run / MIG products, global addresses for GKE Gateways, and DNS A records generated from the registry.
locals {
  armor  = var.cloud_armor
  armor_rules = merge([for pn, p in local.armor : { for r in try(p.rules, []) : "${pn}|${r.priority}" => merge(r, { policy = pn }) }]...)
  inherited   = merge([for pn, p in local.armor : try(p.inherits, null) == null ? {} :
    { for r in local.armor[p.inherits].rules : "${pn}|${r.priority}" => merge(r, { policy = pn }) }]...)
  all_rules = merge(local.inherited, local.armor_rules)
  # certificates are needed in the ingress project (ALBs) and in the GKE project (Gateways); one DNS authorisation
  # per project with PER_PROJECT_RECORD so both can coexist in the zone (T-N10)
  alb_certs = toset([for a in values(var.albs) : a.certificate])
  gw_certs  = toset([for g in values(var.gateway_addresses) : g.certificate])
  certs = merge(
    { for c in local.alb_certs : "${var.ingress_project}|${c}" => merge(var.certificates[c], { project = var.ingress_project, key = c }) },
    { for c in local.gw_certs : "${var.gke_project}|${c}" => merge(var.certificates[c], { project = var.gke_project, key = c }) }
  )
}

# --- Cloud Armor (in the ingress project; T-N11 confirms attachment to cross-project backends) ---
resource "google_compute_security_policy" "this" {
  for_each = local.armor
  project  = var.ingress_project
  name     = each.key
  type     = "CLOUD_ARMOR"
  rule {
    action   = each.value.default_action
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "default"
  }
}

resource "google_compute_security_policy_rule" "this" {
  for_each        = local.all_rules
  project         = var.ingress_project
  security_policy = google_compute_security_policy.this[each.value.policy].name
  priority        = each.value.priority
  action          = each.value.action == "throttle" ? "throttle" : each.value.action
  dynamic "match" {
    for_each = try(each.value.expression, null) != null ? [1] : []
    content {
      expr {
        expression = each.value.expression
      }
    }
  }
  dynamic "match" {
    for_each = try(each.value.expression, null) == null ? [1] : []
    content {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = try(each.value.src_ip_ranges, "") == "@customer_uat_allowlist" ? var.uat_allowlist : ["*"]
      }
    }
  }
  dynamic "rate_limit_options" {
    for_each = each.value.action == "throttle" ? [each.value.rate_limit] : []
    content {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = rate_limit_options.value.key
      rate_limit_threshold {
        count        = rate_limit_options.value.count
        interval_sec = rate_limit_options.value.interval_sec
      }
    }
  }
}

# --- Certificates: wildcard per product per tier with DNS authorisation ---
resource "google_certificate_manager_dns_authorization" "this" {
  for_each = local.certs
  project  = each.value.project
  name     = "dnsauth-${each.value.key}"
  domain   = trimprefix(each.value.domain, "*.")
  type     = "PER_PROJECT_RECORD"
}

resource "google_dns_record_set" "dns_auth" {
  for_each     = local.certs
  project      = var.host_project
  managed_zone = each.value.dns_authorization_zone
  name         = google_certificate_manager_dns_authorization.this[each.key].dns_resource_record[0].name
  type         = google_certificate_manager_dns_authorization.this[each.key].dns_resource_record[0].type
  ttl          = 300
  rrdatas      = [google_certificate_manager_dns_authorization.this[each.key].dns_resource_record[0].data]
}

resource "google_certificate_manager_certificate" "this" {
  for_each = local.certs
  project  = each.value.project
  name     = "cert-${each.value.key}"
  managed {
    domains            = [each.value.domain]
    dns_authorizations = [google_certificate_manager_dns_authorization.this[each.key].id]
  }
}

resource "google_certificate_manager_certificate_map" "this" {
  for_each = local.certs
  project  = each.value.project
  name     = "cm-${each.value.key}"
}

resource "google_certificate_manager_certificate_map_entry" "this" {
  for_each     = local.certs
  project      = each.value.project
  name         = "cme-${each.value.key}"
  map          = google_certificate_manager_certificate_map.this[each.key].name
  hostname     = each.value.domain
  certificates = [google_certificate_manager_certificate.this[each.key].id]
}

# --- ALB per product per environment (Cloud Run / MIG) ---
resource "google_compute_global_address" "alb" {
  for_each = var.albs
  project  = var.ingress_project
  name     = each.value.address
}

resource "google_compute_url_map" "this" {
  for_each = var.albs
  project  = var.ingress_project
  name     = each.key
  default_url_redirect {           # unknown hosts get no backend (A6)
    host_redirect = "www.${var.domain}"
    strip_query   = true
  }
  dynamic "host_rule" {
    for_each = each.value.host_rules
    content {
      hosts        = [host_rule.value.host]
      path_matcher = replace(host_rule.value.host, ".", "-")
    }
  }
  dynamic "path_matcher" {
    for_each = each.value.host_rules
    content {
      name            = replace(path_matcher.value.host, ".", "-")
      default_service = "projects/${path_matcher.value.backend_project}/global/backendServices/${path_matcher.value.backend_service}"
    }
  }
}

resource "google_compute_target_https_proxy" "this" {
  for_each        = var.albs
  project         = var.ingress_project
  name            = "https-${each.key}"
  url_map         = google_compute_url_map.this[each.key].id
  certificate_map = "//certificatemanager.googleapis.com/${google_certificate_manager_certificate_map.this["${var.ingress_project}|${each.value.certificate}"].id}"
  ssl_policy      = google_compute_ssl_policy.this.id
}

resource "google_compute_global_forwarding_rule" "https" {
  for_each              = var.albs
  project               = var.ingress_project
  name                  = "fr-https-${each.key}"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = google_compute_global_address.alb[each.key].id
  port_range            = "443"
  target                = google_compute_target_https_proxy.this[each.key].id
}

resource "google_compute_url_map" "redirect" {
  for_each = var.albs
  project  = var.ingress_project
  name     = "redirect-${each.key}"
  default_url_redirect {
    https_redirect = true
    strip_query    = false
  }
}

resource "google_compute_target_http_proxy" "redirect" {
  for_each = var.albs
  project  = var.ingress_project
  name     = "http-${each.key}"
  url_map  = google_compute_url_map.redirect[each.key].id
}

resource "google_compute_global_forwarding_rule" "http" {
  for_each              = var.albs
  project               = var.ingress_project
  name                  = "fr-http-${each.key}"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = google_compute_global_address.alb[each.key].id
  port_range            = "80"
  target                = google_compute_target_http_proxy.redirect[each.key].id
}

resource "google_compute_ssl_policy" "this" {
  project         = var.ingress_project
  name            = "tls-${var.tier}"
  profile         = var.tls_profile
  min_tls_version = var.min_tls_version
}

# --- GKE Gateway addresses (the Gateway objects themselves are created by the cluster-config stack) ---
resource "google_compute_global_address" "gateway" {
  for_each = var.gateway_addresses
  project  = each.value.project
  name     = each.value.address
}

# --- DNS A records, one per hostname (IN01) ---
resource "google_dns_record_set" "host" {
  for_each     = { for r in var.records : r.hostname => r }
  project      = var.host_project
  managed_zone = each.value.zone
  name         = "${each.key}."
  type         = "A"
  ttl          = each.value.ttl
  rrdatas = [startswith(each.value.frontend, "gw-") ? google_compute_global_address.gateway[each.value.frontend].address :
  google_compute_global_address.alb[each.value.frontend].address]
}
