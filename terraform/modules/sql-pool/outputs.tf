output "connection_name" {
  description = "Instance connection name <project>:<region>:<instance> (Helm interface: Cloud SQL Auth Proxy)."
  value       = google_sql_database_instance.this.connection_name
}

output "private_ip" {
  description = "Private IP of the instance."
  value       = google_sql_database_instance.this.private_ip_address
}

output "dr_connection_name" {
  description = "Connection name of the DR replica (null when regional DR is not active)."
  value       = one(google_sql_database_instance.dr[*].connection_name)
}
