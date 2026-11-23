# Workload Identity Federation for CI (D6): one pool in bootstrap-seed, GitHub provider pinned to the organisation id
# and the composite attribute.gate; each pipeline SA bound to exact gate values. No service-account keys.
locals {
  bindings = merge([for b in var.bindings : { for g in b.gates : "${b.service_account}|${g.repo}:${g.env}:${g.ref}" => { sa = b.service_account, gate = g } }]...)
}

resource "google_iam_workload_identity_pool" "this" {
  project                   = var.pool.project
  workload_identity_pool_id = var.pool.id
  display_name              = "CI pipelines"
}

resource "google_iam_workload_identity_pool_provider" "this" {
  for_each                           = var.providers_config
  project                            = var.pool.project
  workload_identity_pool_id          = google_iam_workload_identity_pool.this.workload_identity_pool_id
  workload_identity_pool_provider_id = each.key
  attribute_condition                = replace(replace(replace(each.value.attribute_condition, "$${GH_ORG_ID}", var.github_org_id), "$${GH_ORG}", var.github_org), "\n", " ")
  attribute_mapping                  = { for k, v in each.value.attribute_mapping : k => replace(v, "\n", " ") }
  oidc {
    issuer_uri = each.value.issuer
  }
}

data "google_project" "pool" {
  project_id = var.pool.project
}

resource "google_service_account_iam_member" "this" {
  for_each           = local.bindings
  service_account_id = "projects/${split("@", split(".iam", each.value.sa)[0])[1]}/serviceAccounts/${each.value.sa}"
  role               = "roles/iam.workloadIdentityUser"
  member = join("", ["principalSet://iam.googleapis.com/projects/${data.google_project.pool.number}/locations/global/",
    "workloadIdentityPools/${var.pool.id}/attribute.gate/",
  "${var.repository_ids[each.value.gate.repo]}:${each.value.gate.env}:${each.value.gate.ref}"])
}
