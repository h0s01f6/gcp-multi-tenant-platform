# Per-cell platform Kubernetes configuration (tf-<tier>), applied after the cell exists and before any Helm release.
# Input: build/tfvars/cluster-config/<cell> + build/k8s/<cell>/*.yaml + policies/k8s/constraint-templates.yaml.
provider "google" {}

data "google_client_config" "this" {}

data "google_container_cluster" "this" {
  project  = var.project
  name     = var.cell
  location = var.region
}

provider "kubernetes" {
  host  = "https://${data.google_container_cluster.this.control_plane_endpoints_config[0].dns_endpoint_config[0].endpoint}"
  token = data.google_client_config.this.access_token
}

module "manifests" {
  source                    = "../../modules/k8s-manifests"
  manifests_dir             = "${var.repo_root}/${var.manifests_dir}"
  constraint_templates_file = "${var.repo_root}/policies/k8s/constraint-templates.yaml"
  gateways                  = var.gateways
}
