output "gateways" {
  description = "Gateway name -> namespace (Helm interface: HTTPRoute parentRef)."
  value       = { for k, g in kubernetes_manifest.gateway : k => "gateway-infra" }
}

output "namespaces" {
  description = "Namespaces created from the D8 baseline."
  value       = [for d in values(local.first) : d.metadata.name if d.kind == "Namespace"]
}
