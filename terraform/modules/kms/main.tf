# CMEK key rings and keys (D9). Only Google service agents get encrypt/decrypt; project numbers resolved here.
locals {
  keys    = { for k in var.keys : k.id => k }
  rings   = { for k in var.keys : "${k.project}/${k.key_ring}" => { project = k.project, name = k.key_ring, location = k.location }... }
  members = merge([for k in var.keys : { for m in k.encrypter_decrypter : "${k.id}|${m.format}|${coalesce(m.project, "-")}" => merge(m, { key = k.id }) }]...)
  projects = toset([for m in values(local.members) : m.project if m.project != null])
}

resource "google_kms_key_ring" "this" {
  for_each = { for k, v in local.rings : k => v[0] if var.create_key_rings }
  project  = each.value.project
  name     = each.value.name
  location = each.value.location
}

resource "google_kms_crypto_key" "this" {
  for_each                   = local.keys
  name                       = each.value.key
  key_ring                   = "projects/${each.value.project}/locations/${each.value.location}/keyRings/${each.value.key_ring}"
  purpose                    = each.value.purpose
  rotation_period            = each.value.rotation_period
  destroy_scheduled_duration = each.value.destroy_scheduled_duration
  version_template {
    algorithm        = "GOOGLE_SYMMETRIC_ENCRYPTION"
    protection_level = each.value.protection_level
  }
  lifecycle {
    prevent_destroy = true
  }
  depends_on = [google_kms_key_ring.this]
}

data "google_project" "agent" {
  for_each   = local.projects
  project_id = each.key
}

resource "google_kms_crypto_key_iam_member" "agent" {
  for_each      = local.members
  crypto_key_id = google_kms_crypto_key.this[each.value.key].id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${each.value.project == null ? each.value.format : format(each.value.format, data.google_project.agent[each.value.project].number)}"
}
