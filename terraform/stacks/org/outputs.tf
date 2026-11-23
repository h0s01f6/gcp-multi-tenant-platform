output "folder_ids" {
  description = "Folder name -> folders/<id> (read by tier stacks through terraform_remote_state)."
  value       = module.folders.ids
}

output "artifact_registry" {
  description = "Repository -> Docker URL prefix (Helm interface: image.repository)."
  value       = { for k, r in google_artifact_registry_repository.this : k => "${var.region}-docker.pkg.dev/${r.project}/${r.repository_id}" }
}

output "attestor" {
  description = "Binary Authorization attestor."
  value       = module.attestor.attestor
}

output "wif_providers" {
  description = "WIF provider names for CI workflows."
  value       = module.wif.provider_names
}
