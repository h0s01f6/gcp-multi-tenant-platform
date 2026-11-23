# One pooled Cloud SQL for MySQL 8.4 instance (ADR-003/011): private IP only, connectors enforced, IAM database
# authentication, CMEK in prod (D9), backups + PITR, deletion protection. Databases, roles and grants are created
# by the db-bootstrap job (D4), not here; IAM users are created by the tenant/product stacks.
resource "google_sql_database_instance" "this" {
  project             = var.pool.project
  name                = var.pool.pool
  region              = var.region
  database_version    = var.pool.database_version
  encryption_key_name = var.pool.kms_key
  deletion_protection = true

  settings {
    edition                     = var.pool.edition
    tier                        = var.machine_tier
    availability_type           = var.pool.availability
    connector_enforcement       = var.pool.connector_enforcement
    deletion_protection_enabled = true
    user_labels                 = { pool = var.pool.pool, env = var.pool.env, env_tier = var.pool.tier }

    ip_configuration {
      ipv4_enabled       = var.pool.ipv4_enabled
      private_network    = "projects/${var.host_project}/global/networks/${var.pool.private_network}"
      allocated_ip_range = var.pool.allocated_ip_range
      ssl_mode           = var.pool.ssl_mode
    }

    backup_configuration {
      enabled                        = true
      binary_log_enabled             = true
      start_time                     = "20:30"
      transaction_log_retention_days = 7
      location                       = try(var.pool.backup_location, null) # Stage 8: second region once DR is active (T-DR3)
      backup_retention_settings {
        retained_backups = var.pool.env == "prd" ? 30 : 7
      }
    }

    database_flags {
      name  = "cloudsql_iam_authentication"
      value = "on"
    }

    maintenance_window {
      day  = 7
      hour = 21
    }
  }
}

# Human DBA groups via Cloud SQL IAM group authentication (mechanism 2, D3/AC06).
resource "google_sql_user" "dba_group" {
  for_each = toset(var.dba_groups)
  project  = var.pool.project
  instance = google_sql_database_instance.this.name
  name     = each.key
  type     = "CLOUD_IAM_GROUP"
}

# Stage 8 (slo/dr.yaml regional_dr): pilot-light cross-region read replica, promoted by runbook R-3 when the region
# is lost. Created only when the platform tfvars carry `dr` for the pool (regional DR activated – Q10, BC04).
resource "google_sql_database_instance" "dr" {
  count                = var.dr == null ? 0 : 1
  project              = var.pool.project
  name                 = "${var.pool.pool}-dr"
  region               = var.dr.region
  database_version     = var.pool.database_version
  master_instance_name = google_sql_database_instance.this.name
  encryption_key_name  = var.dr.kms_key
  deletion_protection  = true

  replica_configuration {
    failover_target = false
  }

  settings {
    edition                     = var.pool.edition
    tier                        = var.machine_tier
    availability_type           = "ZONAL" # made REGIONAL after promotion (runbook R-3)
    connector_enforcement       = var.pool.connector_enforcement
    deletion_protection_enabled = true
    user_labels                 = { pool = var.pool.pool, env = var.pool.env, env_tier = var.pool.tier, role = "dr-replica" }

    ip_configuration {
      ipv4_enabled       = false
      private_network    = "projects/${var.host_project}/global/networks/${var.pool.private_network}"
      allocated_ip_range = var.pool.allocated_ip_range
      ssl_mode           = var.pool.ssl_mode
    }

    database_flags {
      name  = "cloudsql_iam_authentication"
      value = "on"
    }
  }
}
