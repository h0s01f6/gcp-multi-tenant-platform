# Tier network (N2–N4): VPC, subnets, PSA, Cloud NAT, network firewall policy + secure tags, DNS zones, subnet IAM.
locals {
  subnets   = { for s in var.subnets : s.name => s }
  tag_pairs = merge([for k, vals in var.secure_tags.keys : { for v in vals : "${k}=${v}" => { key = k, value = v } }]...)
  rules     = { for r in var.firewall_policy.rules : tostring(r.priority) => r }
  priv_recs = merge([for z in var.private_zones : { for r in z.records : "${z.name}|${r.name}|${r.type}" => merge(r, { zone = z.name, dns_name = z.dns_name }) }]...)
  agent_projects = toset([for h in var.host_bindings : h.project])
}

resource "google_compute_network" "vpc" {
  project                                   = var.host_project
  name                                      = var.vpc.name
  routing_mode                              = var.vpc.routing_mode
  mtu                                       = var.vpc.mtu
  auto_create_subnetworks                   = false
  network_firewall_policy_enforcement_order = "AFTER_CLASSIC_FIREWALL"
}

resource "google_compute_subnetwork" "this" {
  for_each                 = local.subnets
  project                  = var.host_project
  name                     = each.key
  region                   = each.value.region
  network                  = google_compute_network.vpc.id
  ip_cidr_range            = each.value.cidr
  private_ip_google_access = each.value.private_google_access
  dynamic "secondary_ip_range" {
    for_each = each.value.secondary
    content {
      range_name    = secondary_ip_range.value.range_name
      ip_cidr_range = secondary_ip_range.value.cidr
    }
  }
}

# --- Cloud SQL private connectivity (private services access) ---
resource "google_compute_global_address" "psa" {
  project       = var.host_project
  name          = var.psa.range_name
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  address       = split("/", var.psa.cidr)[0]
  prefix_length = tonumber(split("/", var.psa.cidr)[1])
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "psa" {
  network                 = google_compute_network.vpc.id
  service                 = var.psa.service
  reserved_peering_ranges = [google_compute_global_address.psa.name]
}

# --- Cloud NAT with static egress IPs ---
resource "google_compute_router" "this" {
  project = var.host_project
  name    = var.nat.router
  region  = var.region
  network = google_compute_network.vpc.id
}

resource "google_compute_address" "nat" {
  count   = var.nat.static_ips
  project = var.host_project
  name    = "${var.nat.name}-ip-${count.index + 1}"
  region  = var.region
}

resource "google_compute_router_nat" "this" {
  project                             = var.host_project
  name                                = var.nat.name
  router                              = google_compute_router.this.name
  region                              = var.region
  nat_ip_allocate_option              = "MANUAL_ONLY"
  nat_ips                             = google_compute_address.nat[*].self_link
  source_subnetwork_ip_ranges_to_nat  = "LIST_OF_SUBNETWORKS"
  enable_dynamic_port_allocation      = var.nat.dynamic_port_allocation
  min_ports_per_vm                    = var.nat.min_ports_per_vm
  max_ports_per_vm                    = var.nat.max_ports_per_vm
  enable_endpoint_independent_mapping = var.nat.endpoint_independent_mapping
  dynamic "subnetwork" {
    for_each = var.nat.subnets
    content {
      name                    = google_compute_subnetwork.this[subnetwork.value].id
      source_ip_ranges_to_nat = contains(var.nat.include_secondary_ranges_for, subnetwork.value) ? ["ALL_IP_RANGES"] : ["PRIMARY_IP_RANGE"]
    }
  }
  log_config {
    enable = true
    filter = var.nat.log_filter
  }
}

# --- Secure tags (firewall targets) ---
resource "google_tags_tag_key" "this" {
  for_each     = var.secure_tags.keys
  parent       = "projects/${var.host_project}"
  short_name   = each.key
  purpose      = "GCE_FIREWALL"
  purpose_data = { network = "${var.host_project}/${google_compute_network.vpc.name}" }
}

resource "google_tags_tag_value" "this" {
  for_each   = local.tag_pairs
  parent     = google_tags_tag_key.this[each.value.key].id
  short_name = each.value.value
}

# --- Global network firewall policy (N3) ---
resource "google_compute_network_firewall_policy" "this" {
  project = var.host_project
  name    = "fwp-${var.tier}"
}

resource "google_compute_network_firewall_policy_rule" "this" {
  for_each        = local.rules
  project         = var.host_project
  firewall_policy = google_compute_network_firewall_policy.this.name
  priority        = each.value.priority
  direction       = each.value.direction
  action          = each.value.action
  description     = try(each.value.why, null)
  dynamic "target_secure_tags" {
    for_each = try(each.value.target_tags, [])
    content {
      name = google_tags_tag_value.this[target_secure_tags.value].id
    }
  }
  match {
    src_ip_ranges  = try(each.value.src, null)
    dest_ip_ranges = try(each.value.dst, null)
    dest_fqdns     = try(each.value.dst_fqdns, null)
    dynamic "layer4_configs" {
      for_each = length(try(each.value.ports, [])) > 0 ? each.value.ports : ["all"]
      content {
        ip_protocol = layer4_configs.value == "all" ? "all" : split(":", layer4_configs.value)[0]
        ports       = length(split(":", layer4_configs.value)) > 1 ? [split(":", layer4_configs.value)[1]] : null
      }
    }
  }
}

resource "google_compute_network_firewall_policy_association" "this" {
  project           = var.host_project
  name              = "fwp-${var.tier}-${google_compute_network.vpc.name}"
  firewall_policy   = google_compute_network_firewall_policy.this.name
  attachment_target = google_compute_network.vpc.id
}

# --- DNS ---
resource "google_dns_managed_zone" "private" {
  for_each   = { for z in var.private_zones : z.name => z }
  project    = var.host_project
  name       = each.key
  dns_name   = each.value.dns_name
  visibility = "private"
  private_visibility_config {
    networks {
      network_url = google_compute_network.vpc.id
    }
  }
}

resource "google_dns_record_set" "private" {
  for_each     = local.priv_recs
  project      = var.host_project
  managed_zone = google_dns_managed_zone.private[each.value.zone].name
  name         = each.value.name == "*" ? "*.${each.value.dns_name}" : "${each.value.name}.${each.value.dns_name}"
  type         = each.value.type
  ttl          = 300
  rrdatas      = each.value.value
}

resource "google_dns_managed_zone" "public" {
  for_each = var.public_zones
  project  = var.host_project
  name     = each.key
  dns_name = each.value.dns_name
  dnssec_config {
    state = each.value.dnssec ? "on" : "off"
  }
}

# --- Subnet-level Network User and GKE host service agent (D3 / N2) ---
resource "google_compute_subnetwork_iam_member" "this" {
  for_each   = { for b in var.subnet_iam : "${b.subnet}|${b.member}" => b }
  project    = var.host_project
  region     = var.region
  subnetwork = google_compute_subnetwork.this[each.value.subnet].name
  role       = each.value.role
  member     = each.value.member
}

resource "google_project_iam_member" "network_viewer" {
  project = var.host_project
  role    = "roles/compute.networkViewer"
  member  = "group:grp-wl-netusers-${var.tier}@${var.group_domain}"
}

data "google_project" "agent" {
  for_each   = local.agent_projects
  project_id = each.key
}

resource "google_project_iam_member" "host_service_agent" {
  for_each = { for h in var.host_bindings : "${h.project}|${h.role}" => h }
  project  = var.host_project
  role     = each.value.role
  member   = "serviceAccount:${format(each.value.format, data.google_project.agent[each.value.project].number)}"
}
