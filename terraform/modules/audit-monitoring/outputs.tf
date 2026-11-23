output "alert_policies" {
  description = "Alert policy names."
  value       = keys(google_monitoring_alert_policy.this)
}
