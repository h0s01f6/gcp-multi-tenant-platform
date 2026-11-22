output "name" { value = google_container_cluster.this.name }
output "endpoint" {
  value     = google_container_cluster.this.endpoint
  sensitive = true
}
output "workload_pool" { value = "${var.project_id}.svc.id.goog" }
output "node_service_account" { value = google_service_account.nodes.email }
