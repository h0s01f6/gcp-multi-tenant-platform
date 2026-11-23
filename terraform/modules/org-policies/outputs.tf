output "policy_names" {
  description = "Created policy resource names."
  value       = [for p in google_org_policy_policy.this : p.name]
}
