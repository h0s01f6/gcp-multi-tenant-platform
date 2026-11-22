# One VPC Service Controls perimeter per customer around its env projects + data project.
# Even a mistaken IAM grant cannot move this customer's data into another customer's project.
locals {
  resources = [for n in var.project_numbers : "projects/${n}"]
}

resource "google_access_context_manager_service_perimeter" "this" {
  parent                    = "accessPolicies/${var.access_policy_id}"
  name                      = "accessPolicies/${var.access_policy_id}/servicePerimeters/${var.name}"
  title                     = var.name
  perimeter_type            = "PERIMETER_TYPE_REGULAR"
  use_explicit_dry_run_spec = var.dry_run

  # Enforced configuration (omitted while rolling out in dry-run mode).
  dynamic "status" {
    for_each = var.dry_run ? [] : [1]
    content {
      resources           = local.resources
      restricted_services = var.restricted_services

      vpc_accessible_services {
        enable_restriction = false
      }

      # Pooled GKE clusters run outside the perimeter. Their traffic reaches Google APIs
      # from the Shared VPC host network, so admit ONLY this customer's own workload
      # service accounts, and only when the call comes from those host projects.
      dynamic "ingress_policies" {
        for_each = length(var.ingress_source_projects) > 0 && length(var.workload_identities) > 0 ? [1] : []
        content {
          ingress_from {
            identities = var.workload_identities
            dynamic "sources" {
              for_each = var.ingress_source_projects
              content {
                resource = "projects/${sources.value}"
              }
            }
          }
          ingress_to {
            resources = ["*"]
            operations {
              service_name = "*"
            }
          }
        }
      }

      # CI / Terraform identities may manage resources inside the perimeter.
      dynamic "ingress_policies" {
        for_each = length(var.admin_identities) > 0 ? [1] : []
        content {
          ingress_from {
            identities = var.admin_identities
            sources {
              access_level = "*"
            }
          }
          ingress_to {
            resources = ["*"]
            operations {
              service_name = "*"
            }
          }
        }
      }
    }
  }

  # Dry-run configuration: violations are logged, not blocked.
  dynamic "spec" {
    for_each = var.dry_run ? [1] : []
    content {
      resources           = local.resources
      restricted_services = var.restricted_services
    }
  }
}
