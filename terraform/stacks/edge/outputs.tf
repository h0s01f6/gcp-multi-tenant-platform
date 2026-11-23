output "alb_addresses" {
  description = "URL map -> IP."
  value       = module.edge.alb_addresses
}

output "gateway_addresses" {
  description = "Gateway -> address name."
  value       = module.edge.gateway_addresses
}
