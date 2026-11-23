# Cloud Identity groups (D3) and the memberships Terraform owns: group managers, pipeline groups, workload groups.
# Human memberships come from the IdP and are never managed here.
resource "google_cloud_identity_group" "this" {
  for_each     = var.groups
  parent       = "customers/${var.customer_id}"
  display_name = each.key
  labels       = { "cloudidentity.googleapis.com/groups.discussion_forum" = "" }
  group_key {
    id = "${each.key}@${var.group_domain}"
  }
}

data "google_cloud_identity_group_lookup" "existing" {
  for_each = var.manage_groups ? toset([]) : toset([for m in var.memberships : m.group])
  group_key {
    id = "${each.key}@${var.group_domain}"
  }
}

resource "google_cloud_identity_group_membership" "this" {
  for_each = { for m in var.memberships : "${m.group}|${m.member}" => m }
  group    = var.manage_groups ? google_cloud_identity_group.this[each.value.group].id : data.google_cloud_identity_group_lookup.existing[each.value.group].name
  preferred_member_key {
    id = split(":", each.value.member)[1]
  }
  roles {
    name = "MEMBER"
  }
  dynamic "roles" {
    for_each = try(each.value.manager, false) ? [1] : []
    content {
      name = "MANAGER"
    }
  }
}
