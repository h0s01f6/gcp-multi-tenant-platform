# Tenant stack (tf-<tier>), one state per tenant per tier. Input: build/tfvars/tenant/<name>-<tier>.
provider "google" {}

data "terraform_remote_state" "org" {
  backend = "gcs"
  config = {
    bucket = var.org_state_bucket
    prefix = "org"
  }
}

module "workloads" {
  source            = "../../modules/workloads"
  workloads         = var.workloads
  folder_ids        = data.terraform_remote_state.org.outputs.folder_ids
  billing_account   = var.billing_account
  region            = var.region
  host_project      = var.host_project
  placeholder_image = var.placeholder_image
}

# Stage 8: uptime checks per customer host name, in the customer's own prd project (slo/slos.yaml `uptime`).
# Empty for nonprd. The alert on them is one policy per tier in the observability stack.
resource "google_monitoring_uptime_check_config" "host" {
  for_each         = { for u in var.uptime_checks : u.id => u }
  project          = var.workloads.project
  display_name     = "${each.value.host}${each.value.path}"
  period           = each.value.period
  timeout          = each.value.timeout
  selected_regions = each.value.regions
  http_check {
    path         = each.value.path
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }
  monitored_resource {
    type   = "uptime_url"
    labels = { project_id = var.workloads.project, host = each.value.host }
  }
  user_labels = { product = each.value.product, env_tier = var.workloads.tier }
  depends_on  = [module.workloads]
}
