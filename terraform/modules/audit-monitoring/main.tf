# Audit logging and security alerts (D10): Data Access logs, org sink to a locked bucket in shr-security,
# notification channels and log-based alert policies. Only Cloud Logging / Monitoring.
locals {
  audit_org     = { for a in var.audit.audit_configs : a.service => a if a.node == "org" }
  audit_folders = { for a in var.audit.audit_configs : "${a.node}|${a.service}" => a if a.node != "org" }
}

resource "google_organization_iam_audit_config" "this" {
  for_each = local.audit_org
  org_id   = var.org_id
  service  = each.key
  dynamic "audit_log_config" {
    for_each = each.value.log_types
    content {
      log_type = audit_log_config.value
    }
  }
}

resource "google_folder_iam_audit_config" "this" {
  for_each = local.audit_folders
  folder   = var.folder_ids[each.value.node]
  service  = each.value.service
  dynamic "audit_log_config" {
    for_each = each.value.log_types
    content {
      log_type = audit_log_config.value
    }
  }
}

resource "google_logging_project_bucket_config" "audit" {
  project        = var.audit.log_bucket.project
  location       = var.audit.log_bucket.location
  bucket_id      = var.audit.log_bucket.name
  retention_days = var.audit.log_bucket.retention_days
  locked         = var.audit.log_bucket.locked
}

resource "google_logging_organization_sink" "audit" {
  name             = var.audit.sink.name
  org_id           = var.org_id
  include_children = var.audit.sink.include_children
  filter           = var.audit.sink.filter
  destination      = "logging.googleapis.com/${google_logging_project_bucket_config.audit.id}"
}

resource "google_project_iam_member" "sink_writer" {
  project = var.audit.log_bucket.project
  role    = "roles/logging.bucketWriter"
  member  = google_logging_organization_sink.audit.writer_identity
  condition {
    title      = "audit-bucket-only"
    expression = "resource.name.endsWith(\"buckets/${var.audit.log_bucket.name}\")"
  }
}

resource "google_monitoring_notification_channel" "this" {
  for_each     = { for k, c in var.audit.channels : k => c if c.kind == "email" }
  project      = var.audit.log_bucket.project
  display_name = each.key
  type         = "email"
  labels       = { email_address = each.value.address }
}

resource "google_monitoring_alert_policy" "this" {
  for_each     = { for a in var.audit.alert_policies : a.display_name => a }
  project      = each.value.project
  display_name = each.key
  combiner     = "OR"
  severity     = each.value.severity == "page" ? "CRITICAL" : each.value.severity == "ticket" ? "WARNING" : "WARNING"
  conditions {
    display_name = each.key
    condition_matched_log {
      filter = each.value.condition_matched_log.filter
    }
  }
  alert_strategy {
    notification_rate_limit {
      period = each.value.notification_rate_limit
    }
    auto_close = each.value.auto_close
  }
  notification_channels = [for c in each.value.notification_channels : google_monitoring_notification_channel.this[c].id if contains(keys(google_monitoring_notification_channel.this), c)]
  documentation {
    content   = each.value.documentation
    mime_type = "text/markdown"
  }
}
