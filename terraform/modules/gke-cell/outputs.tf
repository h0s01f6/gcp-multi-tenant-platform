output "name" {
  description = "Cluster name (cell)."
  value       = google_container_cluster.this.name
}

output "dns_endpoint" {
  description = "DNS-based control-plane endpoint (cluster-config stack and Helm deploy jobs)."
  value       = google_container_cluster.this.control_plane_endpoints_config[0].dns_endpoint_config[0].endpoint
}

output "workload_pool" {
  description = "Workload Identity pool (<project>.svc.id.goog)."
  value       = "${var.project}.svc.id.goog"
}
