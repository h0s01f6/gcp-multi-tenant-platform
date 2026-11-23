# One GCP project with labels, APIs and (optionally) its Shared VPC attachment (N2: only projects with VPC workloads).
resource "google_project" "this" {
  name            = var.name
  project_id      = var.name
  folder_id       = var.folder_id
  billing_account = var.billing_account
  labels          = var.labels
  deletion_policy = "PREVENT"
}

resource "google_project_service" "this" {
  for_each                   = toset(var.apis)
  project                    = google_project.this.project_id
  service                    = each.key
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_compute_shared_vpc_service_project" "this" {
  count           = var.host_project == null ? 0 : 1
  host_project    = var.host_project
  service_project = google_project.this.project_id
  depends_on      = [google_project_service.this]
}
