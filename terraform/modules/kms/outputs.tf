output "key_ids" {
  description = "Key id (project/ring/key) -> crypto key resource id."
  value       = { for k, v in google_kms_crypto_key.this : k => v.id }
}
