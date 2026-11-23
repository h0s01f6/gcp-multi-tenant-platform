output "sql_connection_names" {
  description = "Pool -> instance connection name (Helm interface: db.instanceConnectionName)."
  value       = { for k, p in module.sql_pools : k => p.connection_name }
}

output "gke_endpoints" {
  description = "Cell -> DNS control-plane endpoint (cluster-config provider, Helm deploy jobs)."
  value       = { for k, c in module.gke_cells : k => c.dns_endpoint }
}

output "workload_pools" {
  description = "Cell -> Workload Identity pool."
  value       = { for k, c in module.gke_cells : k => c.workload_pool }
}
