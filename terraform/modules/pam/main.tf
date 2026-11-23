# PAM entitlements (D7), one per matrix entitlement and resource; approval, justification, notifications required.
resource "google_privileged_access_manager_entitlement" "this" {
  for_each             = { for e in var.entitlements : e.entitlement_id => e }
  entitlement_id       = each.key
  location             = "global"
  parent               = each.value.parent == "org" ? "organizations/${var.org_id}" : var.folder_ids[each.value.parent]
  max_request_duration = each.value.max_request_duration
  eligible_users {
    principals = each.value.eligible_principals
  }
  privileged_access {
    gcp_iam_access {
      resource      = each.value.parent == "org" ? "//cloudresourcemanager.googleapis.com/organizations/${var.org_id}" : "//cloudresourcemanager.googleapis.com/${var.folder_ids[each.value.parent]}"
      resource_type = each.value.parent == "org" ? "cloudresourcemanager.googleapis.com/Organization" : "cloudresourcemanager.googleapis.com/Folder"
      dynamic "role_bindings" {
        for_each = each.value.roles
        content {
          role                 = role_bindings.value
          condition_expression = each.value.condition
        }
      }
    }
  }
  requester_justification_config {
    unstructured {}
  }
  approval_workflow {
    manual_approvals {
      require_approver_justification = true
      steps {
        approvals_needed = each.value.approvals_needed
        approvers {
          principals = each.value.approvers
        }
      }
    }
  }
  additional_notification_targets {
    admin_email_recipients = each.value.notification_recipients
  }
}
