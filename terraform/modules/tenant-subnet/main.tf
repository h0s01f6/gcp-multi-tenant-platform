# Customer-env subnet carved from the env supernet in the Shared VPC host,
# plus the IAM that lets that customer's project (and only it) use it.
resource "google_compute_subnetwork" "this" {
  project                  = var.host_project_id
  name                     = var.name
  region                   = var.region
  network                  = var.network
  ip_cidr_range            = var.cidr
  private_ip_google_access = true

  dynamic "secondary_ip_range" {
    for_each = var.secondary_ranges
    content {
      range_name    = secondary_ip_range.key
      ip_cidr_range = secondary_ip_range.value
    }
  }

  log_config {
    aggregation_interval = "INTERVAL_10_MIN"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

resource "google_compute_subnetwork_iam_member" "users" {
  for_each   = toset(var.network_users)
  project    = var.host_project_id
  region     = var.region
  subnetwork = google_compute_subnetwork.this.name
  role       = "roles/compute.networkUser"
  member     = each.value
}
