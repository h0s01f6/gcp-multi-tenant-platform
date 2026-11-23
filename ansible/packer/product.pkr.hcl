# Stage 7 – VM image bake for MIG products (bake-vm-image.yml): runs in shr-build as builder@shr-build,
# provisions with playbooks/bake-image.yml (Stage 6 roles base + app). Status: implemented, not run (T-AN1).
packer {
  required_plugins {
    googlecompute = { source = "github.com/hashicorp/googlecompute", version = "~> 1.1" }
    ansible       = { source = "github.com/hashicorp/ansible", version = "~> 1.1" }
  }
}

variable "product" { type = string }
variable "version" { type = string }      # git tag vX.Y.Z
variable "artifact_url" { type = string } # digest-pinned application artifact (release repository)

locals {
  v = replace(trimprefix(var.version, "v"), ".", "-")
}

source "googlecompute" "product" {
  project_id              = "shr-build"
  zone                    = "asia-south1-a"
  source_image_family     = "debian-12"
  source_image_project_id = ["debian-cloud"]
  image_name              = "${var.product}-${local.v}"
  image_family            = var.product
  image_labels            = { product = var.product, version = local.v }
  machine_type            = "e2-standard-2"
  subnetwork              = "projects/net-host-nonprd/regions/asia-south1/subnetworks/snet-nonprd-as1-mig"
  omit_external_ip        = true
  use_internal_ip         = true
  use_iap                 = true
  use_os_login            = true
  enable_secure_boot          = true
  enable_vtpm                 = true
  enable_integrity_monitoring = true
  ssh_username = "packer"
}

build {
  sources = ["source.googlecompute.product"]
  provisioner "ansible" {
    playbook_file   = "playbooks/bake-image.yml"
    extra_arguments = ["--extra-vars", "product=${var.product} app_version=${trimprefix(var.version, "v")} artifact_url=${var.artifact_url}"]
  }
}
