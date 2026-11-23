output "gateways" {
  description = "Gateway -> namespace (Helm interface: route.gateway)."
  value       = module.manifests.gateways
}

output "namespaces" {
  description = "Namespaces created (Helm releases may only target these)."
  value       = module.manifests.namespaces
}
