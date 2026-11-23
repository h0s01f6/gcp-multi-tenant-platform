output "count" {
  description = "Number of bindings managed."
  value       = length(local.b)
}
