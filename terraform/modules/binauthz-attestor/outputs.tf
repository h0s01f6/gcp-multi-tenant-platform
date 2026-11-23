output "attestor" {
  description = "Attestor resource name (Binary Authorization policies)."
  value       = google_binary_authorization_attestor.this.id
}
