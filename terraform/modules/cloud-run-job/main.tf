# Platform Cloud Run job inside the tier VPC (D4: db-bootstrap in each pool project, db-isotest in shr-cicd-<tier>).
# Image and arguments are set by the pipeline that runs the job; Terraform owns identity and network only.
resource "google_cloud_run_v2_job" "this" {
  project  = var.job.project
  name     = var.job.job
  location = var.region
  template {
    template {
      service_account = var.service_account
      max_retries     = 0
      timeout         = "3600s"
      containers {
        image = var.image
      }
      vpc_access {
        egress = var.job.egress == "all-traffic" ? "ALL_TRAFFIC" : "PRIVATE_RANGES_ONLY"
        network_interfaces {
          network    = "projects/${var.host_project}/global/networks/${var.job.network}"
          subnetwork = "projects/${var.host_project}/regions/${var.region}/subnetworks/${var.job.subnet}"
          tags       = var.job.network_tags
        }
      }
    }
  }
  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, template[0].template[0].containers[0].args]
  }
}
