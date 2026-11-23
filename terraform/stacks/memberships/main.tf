# Workload group memberships (groups-mgr-<tier>, manager of the grp-wl-*-<tier> groups only – D6).
provider "google" {}

locals {
  projects = toset([for m in var.memberships : m.project if m.project != null])
  # tier guard: this stack's identity is manager of its own tier's workload groups only
  foreign = [for m in var.memberships : m.group if !endswith(m.group, var.tier) && !strcontains(m.group, "-${var.tier}-")]
}

check "tier_only" {
  assert {
    condition     = length(local.foreign) == 0
    error_message = "memberships of another tier: ${join(", ", local.foreign)}"
  }
}

data "google_project" "agent" {
  for_each   = local.projects
  project_id = each.key
}

module "memberships" {
  source        = "../../modules/groups"
  customer_id   = "unused"
  group_domain  = var.group_domain
  manage_groups = false
  memberships = [for m in var.memberships : {
    group  = m.group
    member = m.member != null ? m.member : "serviceAccount:${format(m.format, data.google_project.agent[m.project].number)}"
  }]
}
