output "network_id" {
  description = "VPC id."
  value       = module.network.network_id
}

output "subnets" {
  description = "Subnet self links."
  value       = module.network.subnets
}

output "nat_ips" {
  description = "Static egress IPs."
  value       = module.network.nat_ips
}

output "public_zone_names" {
  description = "Public zones."
  value       = module.network.public_zone_names
}
