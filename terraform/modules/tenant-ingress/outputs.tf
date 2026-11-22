output "ip_address" { value = google_compute_global_address.this.address }
output "hosts" { value = { for k, b in var.backends : k => b.host } }
