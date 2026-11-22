# Builds one golden image per product version on the shared Ansible runners:
#   packer build -var product=legacy-erp -var version=7.3.0 packer/product-image.pkr.hcl
packer {
  required_plugins {
    googlecompute = { source = "github.com/hashicorp/googlecompute", version = ">= 1.1.0" }
    ansible       = { source = "github.com/hashicorp/ansible", version = ">= 1.1.0" }
  }
}

variable "product" { type = string }
variable "version" { type = string }
variable "project_id" {
  type    = string
  default = "mtp-artifacts"
}

source "googlecompute" "product" {
  project_id          = var.project_id
  zone                = "asia-south1-a"
  source_image_family = "ubuntu-2404-lts-amd64"
  image_name          = "${var.product}-${replace(var.version, ".", "-")}"
  image_family        = var.product
  image_labels        = { product = var.product, version = replace(var.version, ".", "_") }
  machine_type        = "e2-standard-2"
  subnetwork          = "platform-prod"
  omit_external_ip    = true
  use_internal_ip     = true
  use_iap             = true
  ssh_username        = "packer"
}

build {
  sources = ["source.googlecompute.product"]
  provisioner "ansible" {
    playbook_file   = "${path.root}/../ansible/playbooks/bake-image.yml"
    extra_arguments = ["--extra-vars", "product=${var.product} version=${var.version}"]
    use_proxy       = false
  }
}
