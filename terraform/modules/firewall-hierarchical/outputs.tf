output "policy_ids" {
  description = "Policy name -> id."
  value       = { for k, p in google_compute_firewall_policy.this : k => p.id }
}
