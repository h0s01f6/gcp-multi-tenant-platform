output "scoping_projects" {
  description = "Metrics scoping projects of the tier."
  value       = { for k, m in module.scoping_projects : k => m.project_id }
}

output "slo_names" {
  description = "SLO resource names (dashboards, error-budget reports)."
  value       = merge({ for k, s in google_monitoring_slo.availability : k => s.name }, { for k, s in google_monitoring_slo.latency : k => s.name })
}
