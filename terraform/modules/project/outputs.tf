output "project_id" {
  description = "Project ID."
  value       = google_project.this.project_id
}

output "number" {
  description = "Project number (service-agent e-mails)."
  value       = google_project.this.number
}
