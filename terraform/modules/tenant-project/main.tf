# A customer-environment project: holds every product that customer runs in that env.
resource "google_project" "this" {
  project_id          = var.project_id
  name                = var.project_id
  folder_id           = var.folder_id
  billing_account     = var.billing_account
  labels              = var.labels
  auto_create_network = false
  deletion_policy     = var.deletion_policy
}

resource "google_project_service" "apis" {
  for_each                   = toset(var.apis)
  project                    = google_project.this.project_id
  service                    = each.value
  disable_on_destroy         = false
  disable_dependent_services = false
}

# Attach as a Shared VPC service project (skipped for the data project).
resource "google_compute_shared_vpc_service_project" "this" {
  count           = var.host_project_id == null ? 0 : 1
  host_project    = var.host_project_id
  service_project = google_project.this.project_id
  depends_on      = [google_project_service.apis]
}

# env tag drives environment-specific org policies (see stacks/1-org).
resource "google_tags_tag_binding" "env" {
  parent    = "//cloudresourcemanager.googleapis.com/projects/${google_project.this.number}"
  tag_value = var.env_tag_value_id
}

resource "google_billing_budget" "this" {
  count           = var.budget_usd == null ? 0 : 1
  billing_account = var.billing_account
  display_name    = "${var.project_id}-monthly"

  budget_filter {
    projects = ["projects/${google_project.this.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.budget_usd)
    }
  }

  threshold_rules { threshold_percent = 0.8 }
  threshold_rules { threshold_percent = 1.0 }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }
}

resource "google_project_iam_member" "support" {
  for_each = toset(var.support_roles)
  project  = google_project.this.project_id
  role     = each.value
  member   = "group:${var.support_group}"
}
