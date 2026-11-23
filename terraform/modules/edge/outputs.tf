output "alb_addresses" {
  description = "URL map -> frontend IP."
  value       = { for k, a in google_compute_global_address.alb : k => a.address }
}

output "gateway_addresses" {
  description = "Gateway name -> global address name (Helm interface: Gateway annotation via cluster-config)."
  value       = { for k, a in google_compute_global_address.gateway : k => a.name }
}

output "certificate_maps" {
  description = "<project>|<certificate key> -> certificate map name (Gateways reference the plt-gke one)."
  value       = { for k, m in google_certificate_manager_certificate_map.this : k => m.name }
}
