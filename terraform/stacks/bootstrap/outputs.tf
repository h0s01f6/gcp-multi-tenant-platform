output "state_buckets" {
  description = "State bucket names (backend configuration of every other stack)."
  value       = { for k, b in google_storage_bucket.state : k => b.name }
}
