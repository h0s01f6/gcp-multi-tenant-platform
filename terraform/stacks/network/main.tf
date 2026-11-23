# Tier network stack (tf-<tier>): everything in net-host-<tier> (N2–N4). Input: build/tfvars/network/<tier>.
provider "google" {}

module "network" {
  source          = "../../modules/network"
  tier            = var.tier
  region          = var.region
  host_project    = var.host_project
  group_domain    = var.group_domain
  vpc             = var.vpc
  subnets         = var.subnets
  psa             = var.psa
  nat             = var.nat
  firewall_policy = var.firewall_policy
  secure_tags     = var.secure_tags
  private_zones   = var.private_zones
  public_zones    = var.public_zones
  subnet_iam      = var.subnet_iam
  host_bindings   = var.host_bindings
}
