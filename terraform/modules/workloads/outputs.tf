output "project_id" {
  description = "Workload project."
  value       = local.p
}

output "service_account_emails" {
  description = "account_id -> e-mail (Helm interface: Workload Identity GSA)."
  value       = { for k, s in google_service_account.this : k => s.email }
}

output "bucket_names" {
  description = "Bucket names (Helm interface)."
  value       = [for b in google_storage_bucket.this : b.name]
}

output "secret_ids" {
  description = "Secret short name -> full resource name (Helm interface: secret references, never values)."
  value       = { for k, s in google_secret_manager_secret.this : k => s.id }
}

output "backend_services" {
  description = "Backend service name -> id (edge stack URL maps)."
  value       = { for k, b in google_compute_backend_service.this : k => b.id }
}

output "sql_users" {
  description = "Cloud SQL IAM users created (Helm interface: DB user = SA local part)."
  value       = [for u in google_sql_user.this : u.name]
}
