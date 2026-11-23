output "group_ids" {
  description = "Group name -> groups/<id>."
  value       = { for k, g in google_cloud_identity_group.this : k => g.id }
}
