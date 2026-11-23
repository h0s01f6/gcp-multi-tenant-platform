output "service_account_emails" {
  description = "Workload SAs (Helm interface)."
  value       = module.workloads.service_account_emails
}

output "secret_ids" {
  description = "Secret resource names (Helm interface)."
  value       = module.workloads.secret_ids
}

output "bucket_names" {
  description = "Buckets (Helm interface)."
  value       = module.workloads.bucket_names
}

output "backend_services" {
  description = "Backend services (edge stack)."
  value       = module.workloads.backend_services
}

output "sql_users" {
  description = "Cloud SQL IAM users (Helm interface)."
  value       = module.workloads.sql_users
}
