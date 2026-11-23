# Folder tree (Stage 2 ADR-002, env-first). Two levels: fldr-<x> under the org, fldr-<x>/<tier> under them.
locals {
  top      = { for f in var.folders : f.name => f if f.parent == "org" }
  children = { for f in var.folders : f.name => f if f.parent != "org" }
}

resource "google_folder" "top" {
  for_each     = local.top
  display_name = each.key
  parent       = "organizations/${var.org_id}"
}

resource "google_folder" "child" {
  for_each     = local.children
  display_name = replace(each.key, "/", "-")
  parent       = google_folder.top[each.value.parent].name
}
