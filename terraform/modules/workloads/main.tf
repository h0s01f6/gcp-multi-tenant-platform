# Everything that lives in one tenant project (t-<tenant>-<tier>) or Shared/Cohort product project (p-<product>-<tier>):
# identities (D2), data stores with CMEK (D9), Cloud SQL IAM users (D4), Cloud Run service shells, MIGs and backend
# services (N2/N4), Binary Authorization policy (D9), isotest impersonation (D4). Values come only from the registry.
locals {
  p          = var.workloads.project
  sas        = { for s in var.workloads.service_accounts : s.account_id => s }
  wi         = { for w in var.workloads.workload_identity_bindings : "${w.service_account_email}|${w.member}" => w }
  sql_users  = { for u in var.workloads.sql_users : "${u.pool}|${u.user}" => u }
  proj_iam   = { for b in var.workloads.project_iam : "${b.role}|${b.member}" => b }
  bucket_iam = { for b in var.workloads.resource_iam : "${b.resource}|${b.role}|${b.member}" => b if b.resource_type == "storage_bucket" }
  secret_iam = { for b in var.workloads.resource_iam : "${b.resource}|${b.role}|${b.member}" => b if b.resource_type == "secret" }
  buckets    = { for b in var.workloads.buckets : b.bucket => b }
  secrets    = { for s in var.workloads.secrets : s.secret_id => s }
  runs       = { for r in var.workloads.cloud_run_services : r.service => r }
  migs       = { for m in var.workloads.migs : m.deployment => m }
  backends   = { for b in var.workloads.backend_services : b.name => b }
  isotest    = { for b in var.workloads.isotest_bindings : "${b.resource}|${b.member}" => b }
  labels     = { env_tier = var.workloads.tier, managed_by = "terraform" }
}

module "project" {
  source          = "../project"
  count           = var.workloads.create_project ? 1 : 0
  name            = local.p
  folder_id       = var.folder_ids[var.workloads.folder]
  billing_account = var.billing_account
  labels          = merge(local.labels, var.project_labels)
  host_project    = var.workloads.host_project
  apis = ["iam.googleapis.com", "secretmanager.googleapis.com", "cloudkms.googleapis.com", "storage.googleapis.com",
  "run.googleapis.com", "compute.googleapis.com", "sqladmin.googleapis.com", "binaryauthorization.googleapis.com"]
}

# --- identities (D2) ---
resource "google_service_account" "this" {
  for_each     = local.sas
  project      = local.p
  account_id   = each.key
  display_name = each.value.display_name
  depends_on   = [module.project]
}

resource "google_service_account_iam_member" "workload_identity" {
  for_each           = local.wi
  service_account_id = "projects/${local.p}/serviceAccounts/${each.value.service_account_email}"
  role               = each.value.role
  member             = each.value.member
  depends_on         = [google_service_account.this]
}

resource "google_service_account_iam_member" "isotest" {
  for_each           = local.isotest
  service_account_id = "projects/${local.p}/serviceAccounts/${each.value.resource}"
  role               = each.value.role
  member             = each.value.member
  depends_on         = [google_service_account.this]
}

resource "google_project_iam_member" "this" {
  for_each = local.proj_iam
  project  = each.value.project
  role     = each.value.role
  member   = each.value.member
}

# Cloud SQL IAM database users on the pooled instances (ISO-09 expects exactly these accounts).
resource "google_sql_user" "this" {
  for_each = local.sql_users
  project  = each.value.pool_project
  instance = each.value.pool
  name     = each.value.sa_email
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
  depends_on = [google_service_account.this]
}

# --- keys, buckets, secrets (D9) ---
module "kms" {
  source     = "../kms"
  keys       = var.workloads.kms_keys
  depends_on = [module.project]
}

resource "google_storage_bucket" "this" {
  for_each                    = local.buckets
  project                     = local.p
  name                        = each.key
  location                    = each.value.location
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = merge(local.labels, { tenant = coalesce(each.value.tenant, "multi") })
  versioning {
    enabled = true
  }
  dynamic "encryption" {
    for_each = each.value.default_kms_key == null ? [] : [each.value.default_kms_key]
    content {
      default_kms_key_name = encryption.value
    }
  }
  depends_on = [module.kms]
}

resource "google_storage_bucket_iam_member" "this" {
  for_each = local.bucket_iam
  bucket   = google_storage_bucket.this[each.value.resource].name
  role     = each.value.role
  member   = each.value.member
}

resource "google_secret_manager_secret" "this" {
  for_each            = local.secrets
  project             = local.p
  secret_id           = each.key
  labels              = each.value.labels
  annotations         = each.value.annotations
  version_destroy_ttl = each.value.version_destroy_ttl
  replication {
    user_managed {
      dynamic "replicas" {
        for_each = each.value.replication.locations
        content {
          location = replicas.value
          dynamic "customer_managed_encryption" {
            for_each = each.value.kms_key == null ? [] : [each.value.kms_key]
            content {
              kms_key_name = customer_managed_encryption.value
            }
          }
        }
      }
    }
  }
  depends_on = [module.kms]
}
# No google_secret_manager_secret_version: values never enter Terraform state (D9, DP05).

resource "google_secret_manager_secret_iam_member" "this" {
  for_each  = local.secret_iam
  project   = local.p
  secret_id = google_secret_manager_secret.this[each.value.resource].secret_id
  role      = each.value.role
  member    = each.value.member
}

# --- Cloud Run service shells (Terraform owns identity, ingress, network; the deploy pipeline owns the image) ---
resource "google_cloud_run_v2_service" "this" {
  for_each            = local.runs
  project             = local.p
  name                = each.key
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  deletion_protection = var.workloads.tier == "prd"
  binary_authorization {
    use_default = true
  }
  template {
    service_account = "${each.key}@${local.p}.iam.gserviceaccount.com"
    containers {
      image = var.placeholder_image
      ports {
        container_port = var.app_port
      }
    }
    vpc_access {
      egress = each.value.egress == "all-traffic" ? "ALL_TRAFFIC" : "PRIVATE_RANGES_ONLY"
      network_interfaces {
        network    = "projects/${var.host_project}/global/networks/${each.value.network}"
        subnetwork = "projects/${var.host_project}/regions/${var.region}/subnetworks/${each.value.subnet}"
        tags       = each.value.network_tags
      }
    }
  }
  lifecycle {
    ignore_changes = [template[0].containers[0].image, template[0].revision, client, client_version]
  }
  depends_on = [google_service_account.this]
}

resource "google_compute_region_network_endpoint_group" "run" {
  for_each              = { for k, b in local.backends : k => b if b.kind == "serverless_neg" }
  project               = local.p
  name                  = "neg-${each.key}"
  region                = var.region
  network_endpoint_type = "SERVERLESS"
  cloud_run {
    service = one([for r in values(local.runs) : r.service if endswith(each.key, r.service)])
  }
  depends_on = [google_cloud_run_v2_service.this]
}

# --- MIG products (template + regional MIG + autoscaling + autohealing) ---
data "google_tags_tag_key" "fw" {
  for_each   = length(local.migs) > 0 ? toset(["wl", "app"]) : toset([])
  parent     = "projects/${var.host_project}"
  short_name = each.key
}

data "google_tags_tag_value" "fw" {
  for_each   = toset(flatten([for m in values(local.migs) : m.secure_tags]))
  parent     = data.google_tags_tag_key.fw[split("=", each.key)[0]].id
  short_name = split("=", each.key)[1]
}

resource "google_compute_health_check" "mig" {
  for_each = local.migs
  project  = local.p
  name     = "hc-${each.key}"
  http_health_check {
    port         = var.app_port
    request_path = var.health_path
  }
}

resource "google_compute_region_instance_template" "mig" {
  for_each     = local.migs
  project      = local.p
  name_prefix  = "it-${each.key}-"
  region       = var.region
  machine_type = var.mig_machine_type
  disk {
    source_image = "projects/shr-build/global/images/family/${split("=", [for t in each.value.secure_tags : t if startswith(t, "app=")][0])[1]}"
    boot         = true
    auto_delete  = true
  }
  network_interface {
    subnetwork = "projects/${var.host_project}/regions/${var.region}/subnetworks/${each.value.subnet}"
    # no access_config block: no external IP (D5 compute.vmExternalIpAccess)
  }
  service_account {
    email  = "${each.key}@${local.p}.iam.gserviceaccount.com"
    scopes = ["cloud-platform"]
  }
  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
  metadata = merge({ enable-oslogin = "TRUE" }, each.value.metadata) # identifiers for the boot-time loader (Ansible app role)
  resource_manager_tags = { for t in each.value.secure_tags : data.google_tags_tag_key.fw[split("=", t)[0]].id => data.google_tags_tag_value.fw[t].id }
  lifecycle {
    create_before_destroy = true
    ignore_changes        = [disk[0].source_image] # image version rolled out by the deploy pipeline (Ansible/Packer)
  }
}

resource "google_compute_region_instance_group_manager" "mig" {
  for_each           = local.migs
  project            = local.p
  name               = "mig-${each.key}"
  region             = var.region
  base_instance_name = each.key
  version {
    instance_template = google_compute_region_instance_template.mig[each.key].self_link
  }
  named_port {
    name = "http"
    port = var.app_port
  }
  auto_healing_policies {
    health_check      = google_compute_health_check.mig[each.key].id
    initial_delay_sec = 300
  }
  update_policy {
    type                  = "PROACTIVE"
    minimal_action        = "REPLACE"
    max_surge_fixed       = 3
    max_unavailable_fixed = 0
  }
  lifecycle {
    # Stage 7 (A-H-2): the deploy pipeline points the MIG at a template pinned to image <product>-<version>;
    # Terraform owns the group, the base template and the policies, not the running version.
    ignore_changes = [version]
  }
}

resource "google_compute_region_autoscaler" "mig" {
  for_each = local.migs
  project  = local.p
  name     = "as-${each.key}"
  region   = var.region
  target   = google_compute_region_instance_group_manager.mig[each.key].id
  autoscaling_policy {
    min_replicas    = var.workloads.tier == "prd" ? 2 : 1
    max_replicas    = var.mig_max_replicas
    cooldown_period = 120
    cpu_utilization {
      target = 0.6
    }
  }
}

# --- backend services referenced by the tier ALB (cross-project service referencing, N4) ---
resource "google_compute_backend_service" "this" {
  for_each              = local.backends
  project               = local.p
  name                  = each.key
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTP"
  port_name             = each.value.kind == "instance_group" ? "http" : null
  health_checks         = each.value.kind == "instance_group" ? [google_compute_health_check.mig[one([for m in keys(local.migs) : m if endswith(each.key, m)])].id] : null
  security_policy       = "projects/plt-ingress-${var.workloads.tier}/global/securityPolicies/${each.value.cloud_armor}"
  log_config {
    enable = true
  }
  backend {
    group = each.value.kind == "serverless_neg" ? google_compute_region_network_endpoint_group.run[each.key].id : google_compute_region_instance_group_manager.mig[one([for m in keys(local.migs) : m if endswith(each.key, m)])].instance_group
  }
}

# Cross-project use of the backend services by the tier ALB (plt-ingress-<tier>).
resource "google_project_iam_member" "lb_service_user" {
  count   = length(local.backends) > 0 ? 1 : 0
  project = local.p
  role    = "roles/compute.loadBalancerServiceUser"
  member  = "serviceAccount:tf-${var.workloads.tier}@shr-cicd-${var.workloads.tier}.iam.gserviceaccount.com"
}

# --- Binary Authorization (D9) ---
resource "google_binary_authorization_policy" "this" {
  count                         = var.workloads.binauthz_policy == null ? 0 : 1
  project                       = local.p
  global_policy_evaluation_mode = var.workloads.binauthz_policy.global_policy_evaluation_mode
  default_admission_rule {
    evaluation_mode         = var.workloads.binauthz_policy.default_admission_rule.evaluation_mode
    enforcement_mode        = var.workloads.binauthz_policy.default_admission_rule.enforcement_mode
    require_attestations_by = var.workloads.binauthz_policy.default_admission_rule.require_attestations_by
  }
  depends_on = [module.project]
}

data "google_project" "this" {
  count      = var.workloads.binauthz_policy == null ? 0 : 1
  project_id = local.p
  depends_on = [module.project]
}

resource "google_binary_authorization_attestor_iam_member" "verifier" {
  count    = var.workloads.binauthz_policy == null ? 0 : 1
  project  = "shr-build"
  attestor = "built-by-shr-build"
  role     = var.workloads.binauthz_policy.verifier.role
  member   = "serviceAccount:${format(var.workloads.binauthz_policy.verifier.format, data.google_project.this[0].number)}"
}
