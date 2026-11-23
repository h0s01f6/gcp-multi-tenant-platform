output "provider_names" {
  description = "Provider resource names (google-github-actions/auth `workload_identity_provider`)."
  value       = { for k, p in google_iam_workload_identity_pool_provider.this : k => p.name }
}
