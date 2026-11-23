output "entitlement_ids" {
  description = "Entitlement ids."
  value       = keys(google_privileged_access_manager_entitlement.this)
}
