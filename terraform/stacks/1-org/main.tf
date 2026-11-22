data "terraform_remote_state" "bootstrap" {
  backend = "gcs"
  config  = { bucket = var.state_bucket, prefix = "0-bootstrap" }
}

locals {
  org     = "organizations/${local.platform.org_id}"
  env_tag = "${local.platform.org_id}/env"
}

resource "google_folder" "top" {
  for_each     = toset(["network", "compute", "tenants"])
  display_name = "fldr-${each.key}"
  parent       = local.org
}

# ---- Environment tag: bound to every project, used as the policy dimension ----
resource "google_tags_tag_key" "env" {
  parent      = local.org
  short_name  = "env"
  description = "Deployment environment of the project"
}

resource "google_tags_tag_value" "env" {
  for_each   = local.envs
  parent     = google_tags_tag_key.env.id
  short_name = each.key
}

# ---- Org-wide guardrails (boolean constraints) ----
resource "google_org_policy_policy" "boolean" {
  for_each = toset([
    "iam.disableServiceAccountKeyCreation",
    "compute.requireOsLogin",
    "compute.requireShieldedVm",
    "compute.skipDefaultNetworkCreation",
    "storage.uniformBucketLevelAccess",
    "storage.publicAccessPrevention",
    "sql.restrictPublicIp",
  ])
  name   = "${local.org}/policies/${each.value}"
  parent = local.org
  spec {
    rules {
      enforce = "TRUE"
    }
  }
}

resource "google_org_policy_policy" "no_external_ip" {
  name   = "${local.org}/policies/compute.vmExternalIpAccess"
  parent = local.org
  spec {
    rules {
      deny_all = "TRUE"
    }
  }
}

resource "google_org_policy_policy" "locations" {
  name   = "${local.org}/policies/gcp.resourceLocations"
  parent = local.org
  spec {
    rules {
      values {
        allowed_values = local.platform.allowed_locations
      }
    }
  }
}

# ---- Environment-specific policy via tags (no duplicated folder trees) ----
# prod-tagged projects must use CMEK for data services.
resource "google_org_policy_policy" "prod_cmek" {
  name   = "${local.org}/policies/gcp.restrictNonCmekServices"
  parent = local.org
  spec {
    rules {
      condition {
        title      = "prod requires CMEK"
        expression = "resource.matchTag('${local.env_tag}', 'prod')"
      }
      values {
        denied_values = ["bigquery.googleapis.com", "storage.googleapis.com", "sqladmin.googleapis.com"]
      }
    }
    rules {
      allow_all = "TRUE"
    }
  }
  depends_on = [google_tags_tag_value.env]
}

# prod Cloud Run services may only be reached through the load balancer.
resource "google_org_policy_policy" "prod_run_ingress" {
  name   = "${local.org}/policies/run.allowedIngress"
  parent = local.org
  spec {
    rules {
      condition {
        title      = "prod: internal + LB only"
        expression = "resource.matchTag('${local.env_tag}', 'prod')"
      }
      values {
        allowed_values = ["is:internal-and-cloud-load-balancing"]
      }
    }
    rules {
      allow_all = "TRUE"
    }
  }
  depends_on = [google_tags_tag_value.env]
}

output "folders" {
  value = merge(
    { for k, f in google_folder.top : k => f.name },
    { platform = data.terraform_remote_state.bootstrap.outputs.platform_folder_id },
  )
}
output "env_tag_values" { value = { for k, v in google_tags_tag_value.env : k => v.id } }
