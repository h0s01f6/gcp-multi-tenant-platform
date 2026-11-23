output "ids" {
  description = "Folder name (e.g. fldr-tenants/prd) -> folders/<id>."
  value       = merge({ for k, f in google_folder.top : k => f.name }, { for k, f in google_folder.child : k => f.name })
}
