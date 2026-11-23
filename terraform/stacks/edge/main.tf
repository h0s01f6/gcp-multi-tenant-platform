# Tier edge stack (tf-<tier>): load balancers, certificates, Cloud Armor, DNS records. Input: build/tfvars/edge/<tier>.
provider "google" {}

module "edge" {
  source            = "../../modules/edge"
  tier              = var.tier
  domain            = var.domain
  host_project      = var.host_project
  ingress_project   = var.ingress_project
  gke_project       = var.gke_project
  albs              = var.albs
  gateway_addresses = var.gateway_addresses
  certificates      = var.certificates
  records           = var.records
  cloud_armor       = var.cloud_armor
  uat_allowlist     = var.uat_allowlist
}
