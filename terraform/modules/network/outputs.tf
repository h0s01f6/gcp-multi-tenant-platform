output "network_id" {
  description = "VPC id (Stage 5 interface: GKE cells, Cloud Run, MIG, Cloud SQL)."
  value       = google_compute_network.vpc.id
}

output "subnets" {
  description = "Subnet name -> self link."
  value       = { for k, s in google_compute_subnetwork.this : k => s.self_link }
}

output "nat_ips" {
  description = "Static egress IPs customers and partners can allow-list."
  value       = google_compute_address.nat[*].address
}

output "public_zone_names" {
  description = "Public zone key -> managed zone name (edge stack records)."
  value       = { for k, z in google_dns_managed_zone.public : k => z.name }
}

output "secure_tag_values" {
  description = "key=value -> tag value id (MIG instance templates)."
  value       = { for k, v in google_tags_tag_value.this : k => v.id }
}

output "psa_connection" {
  description = "Private services access peering (Cloud SQL pools depend on it)."
  value       = google_service_networking_connection.psa.peering
}
