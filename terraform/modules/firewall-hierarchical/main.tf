# Hierarchical firewall policies (N3): fw-org at the organisation, fw-tier-<tier> on both folders of a tier.
locals {
  rules = merge([for pname, p in var.policies : { for r in p.rules : "${pname}|${r.priority}" => merge(r, { policy = pname }) }]...)
  assoc = merge([for pname, p in var.policies : { for a in p.attach : "${pname}|${a}" => { policy = pname, node = a } }]...)
}

resource "google_compute_firewall_policy" "this" {
  for_each   = var.policies
  parent     = "organizations/${var.org_id}"
  short_name = each.key
}

resource "google_compute_firewall_policy_rule" "this" {
  for_each        = local.rules
  firewall_policy = google_compute_firewall_policy.this[each.value.policy].name
  priority        = each.value.priority
  direction       = each.value.direction
  action          = each.value.action
  description     = try(each.value.why, null)
  match {
    src_ip_ranges  = each.value.direction == "INGRESS" ? try(each.value.src, null) : null
    dest_ip_ranges = each.value.direction == "EGRESS" ? try(each.value.dst, null) : null
    dynamic "layer4_configs" {
      for_each = each.value.ports
      content {
        ip_protocol = layer4_configs.value == "all" ? "all" : split(":", layer4_configs.value)[0]
        ports       = length(split(":", layer4_configs.value)) > 1 ? [split(":", layer4_configs.value)[1]] : null
      }
    }
  }
}

resource "google_compute_firewall_policy_association" "this" {
  for_each          = local.assoc
  name              = replace("${each.value.policy}-${each.value.node}", "/", "-")
  firewall_policy   = google_compute_firewall_policy.this[each.value.policy].name
  attachment_target = each.value.node == "org" ? "organizations/${var.org_id}" : var.folder_ids[each.value.node]
}
