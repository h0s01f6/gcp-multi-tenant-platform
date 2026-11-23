# Organisation policies (D5). One google_org_policy_policy per (node, constraint); high-impact ones in dry-run.
locals {
  policies = { for p in var.policies : "${p.node}|${p.constraint}" => p }
  parent   = { for k, p in local.policies : k => p.node == "org" ? "organizations/${var.org_id}" : var.folder_ids[p.node] }
}

resource "google_org_policy_policy" "this" {
  for_each = local.policies
  name     = "${local.parent[each.key]}/policies/${each.value.constraint}"
  parent   = local.parent[each.key]

  dynamic "spec" {
    for_each = each.value.dry_run ? [] : [each.value]
    content {
      rules {
        enforce    = spec.value.kind == "boolean" ? (spec.value.enforce ? "TRUE" : "FALSE") : null
        deny_all   = spec.value.kind == "deny_all" ? "TRUE" : null
        dynamic "values" {
          for_each = contains(["allow", "deny"], spec.value.kind) ? [spec.value] : []
          content {
            allowed_values = values.value.kind == "allow" ? [for v in values.value.values : replace(v, "$${ORG_ID}", var.org_id)] : null
            denied_values  = values.value.kind == "deny" ? values.value.values : null
          }
        }
      }
    }
  }

  dynamic "dry_run_spec" {
    for_each = each.value.dry_run ? [each.value] : []
    content {
      rules {
        enforce  = dry_run_spec.value.kind == "boolean" ? (dry_run_spec.value.enforce ? "TRUE" : "FALSE") : null
        deny_all = dry_run_spec.value.kind == "deny_all" ? "TRUE" : null
        dynamic "values" {
          for_each = contains(["allow", "deny"], dry_run_spec.value.kind) ? [dry_run_spec.value] : []
          content {
            allowed_values = values.value.kind == "allow" ? [for v in values.value.values : replace(v, "$${ORG_ID}", var.org_id)] : null
            denied_values  = values.value.kind == "deny" ? values.value.values : null
          }
        }
      }
    }
  }
}
