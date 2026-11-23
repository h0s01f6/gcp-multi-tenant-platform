# Additive IAM bindings (google_*_iam_member) for every scope type the bridge emits. Never authoritative, so
# bindings made by other stacks are not removed. Conditions (e.g. D9 per-product secrets) are passed through.
locals {
  b = { for x in var.bindings : "${x.scope_type}|${x.scope}|${x.role}|${x.member}" => x }
  by_type = { for t in ["organization", "folder", "project", "billing_account", "artifact_repository", "kms_keyring", "kms_key", "bucket"] :
    t => { for k, x in local.b : k => x if x.scope_type == t } }
}

resource "google_organization_iam_member" "this" {
  for_each = local.by_type["organization"]
  org_id   = var.org_id
  role     = each.value.role
  member   = each.value.member
  dynamic "condition" {
    for_each = each.value.condition == null ? [] : [each.value.condition]
    content {
      title      = "stage3-condition"
      expression = condition.value
    }
  }
}

resource "google_folder_iam_member" "this" {
  for_each = local.by_type["folder"]
  folder   = var.folder_ids[each.value.scope]
  role     = each.value.role
  member   = each.value.member
  dynamic "condition" {
    for_each = each.value.condition == null ? [] : [each.value.condition]
    content {
      title      = "stage3-condition"
      expression = condition.value
    }
  }
}

resource "google_project_iam_member" "this" {
  for_each = local.by_type["project"]
  project  = each.value.scope
  role     = each.value.role
  member   = each.value.member
}

resource "google_billing_account_iam_member" "this" {
  for_each           = local.by_type["billing_account"]
  billing_account_id = var.billing_account
  role               = each.value.role
  member             = each.value.member
}

resource "google_artifact_registry_repository_iam_member" "this" {
  for_each   = local.by_type["artifact_repository"]
  project    = split("/", each.value.scope)[1]
  location   = split("/", each.value.scope)[3]
  repository = split("/", each.value.scope)[5]
  role       = each.value.role
  member     = each.value.member
}

resource "google_kms_key_ring_iam_member" "this" {
  for_each    = local.by_type["kms_keyring"]
  key_ring_id = each.value.scope
  role        = each.value.role
  member      = each.value.member
}

resource "google_kms_crypto_key_iam_member" "this" {
  for_each      = local.by_type["kms_key"]
  crypto_key_id = each.value.scope
  role          = each.value.role
  member        = each.value.member
}

resource "google_storage_bucket_iam_member" "this" {
  for_each = local.by_type["bucket"]
  bucket   = each.value.scope
  role     = each.value.role
  member   = each.value.member
}
