# Observability stack (tf-<tier>), one state per tier (Stage 8). Input: build/tfvars/observability/<tier>
# (tools/slo/observability.py from slo/slos.yaml + registry). Uptime checks live in the tenant stack (customer project).
provider "google" {}

data "terraform_remote_state" "org" {
  backend = "gcs"
  config = {
    bucket = var.org_state_bucket
    prefix = "org"
  }
}

# Scoping projects plt-obs-<tier>-NN (K27: per tier, in the platform folder; <= 375 monitored projects each)
module "scoping_projects" {
  source          = "../../modules/project"
  for_each        = { for p in var.scoping_projects : p.name => p }
  name            = each.key
  folder_id       = data.terraform_remote_state.org.outputs.folder_ids[each.value.folder]
  billing_account = var.billing_account
  labels          = { env_tier = var.tier, purpose = "observability" }
  apis            = ["monitoring.googleapis.com", "logging.googleapis.com"]
}

resource "google_monitoring_monitored_project" "this" {
  for_each      = { for m in var.monitored_projects : "${m.scope}/${m.project}" => m }
  metrics_scope = module.scoping_projects[each.value.scope].project_id
  name          = each.value.project
}

resource "google_monitoring_notification_channel" "this" {
  for_each     = { for c in var.channels : "${c.scope}/${c.id}" => c }
  project      = module.scoping_projects[each.value.scope].project_id
  display_name = each.value.id
  type         = each.value.type
  labels       = { email_address = each.value.address }
}

# Per-customer SLI of Shared / Cohort products: log-based metrics on the LB request logs (slo/slos.yaml sli.shared)
resource "google_logging_metric" "this" {
  for_each = { for m in var.log_metrics : "${m.project}/${m.name}" => m }
  project  = each.value.project
  name     = each.value.name
  filter   = each.value.filter
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = each.value.kind == "distribution" ? "DISTRIBUTION" : "INT64"
    unit        = each.value.kind == "distribution" ? "s" : "1"
    dynamic "labels" {
      for_each = each.value.labels
      content {
        key        = labels.key
        value_type = "STRING"
      }
    }
  }
  label_extractors = each.value.labels
  value_extractor  = each.value.value_extractor
  dynamic "bucket_options" {
    for_each = each.value.kind == "distribution" ? [1] : []
    content {
      exponential_buckets {
        num_finite_buckets = 32
        growth_factor      = 1.5
        scale              = 0.01
      }
    }
  }
}

resource "google_monitoring_custom_service" "this" {
  for_each     = { for s in var.services : s.id => s }
  project      = module.scoping_projects[each.value.scope].project_id
  service_id   = each.key
  display_name = "${each.value.product} (${var.tier})"
  user_labels  = { product = each.value.product }
}

resource "google_monitoring_slo" "availability" {
  for_each            = { for s in var.slos : "${s.service}/${s.id}" => s if s.type == "availability" }
  project             = google_monitoring_custom_service.this[each.value.service].project
  service             = google_monitoring_custom_service.this[each.value.service].service_id
  slo_id              = each.value.id
  display_name        = "${each.value.tenant} ${each.value.product} availability"
  goal                = each.value.goal
  rolling_period_days = each.value.rolling_days
  user_labels         = { tenant = each.value.tenant, product = each.value.product }
  request_based_sli {
    good_total_ratio {
      good_service_filter  = each.value.good_filter
      total_service_filter = each.value.total_filter
    }
  }
}

resource "google_monitoring_slo" "latency" {
  for_each            = { for s in var.slos : "${s.service}/${s.id}" => s if s.type == "latency" }
  project             = google_monitoring_custom_service.this[each.value.service].project
  service             = google_monitoring_custom_service.this[each.value.service].service_id
  slo_id              = each.value.id
  display_name        = "${each.value.tenant} ${each.value.product} latency < ${each.value.threshold_ms} ms"
  goal                = each.value.goal
  rolling_period_days = each.value.rolling_days
  user_labels         = { tenant = each.value.tenant, product = each.value.product }
  request_based_sli {
    distribution_cut {
      distribution_filter = each.value.latency_filter
      range {
        max = each.value.threshold_ms
      }
    }
  }
}

# Burn-rate (per product, grouped by customer), uptime and platform alerts
resource "google_monitoring_alert_policy" "this" {
  for_each              = { for a in var.alert_policies : a.id => a }
  project               = module.scoping_projects[each.value.scope].project_id
  display_name          = each.value.display_name
  combiner              = "OR"
  severity              = each.value.severity == "page" ? "CRITICAL" : "WARNING"
  notification_channels = [for c in each.value.channels : google_monitoring_notification_channel.this["${each.value.scope}/${c}"].id]
  user_labels           = { severity = each.value.severity, tier = var.tier }

  dynamic "conditions" {
    for_each = each.value.conditions
    content {
      display_name = conditions.value.name
      dynamic "condition_prometheus_query_language" {
        for_each = try(conditions.value.promql, null) == null ? [] : [1]
        content {
          query               = conditions.value.promql
          duration            = conditions.value.duration
          evaluation_interval = "60s"
        }
      }
      dynamic "condition_threshold" {
        for_each = try(conditions.value.filter, null) == null ? [] : [1]
        content {
          filter          = conditions.value.filter
          comparison      = "COMPARISON_${conditions.value.comparison}"
          threshold_value = conditions.value.threshold
          duration        = conditions.value.duration
          aggregations {
            alignment_period   = "300s"
            per_series_aligner = conditions.value.aligner
          }
        }
      }
      dynamic "condition_matched_log" {
        for_each = try(conditions.value.log_filter, null) == null ? [] : [1]
        content {
          filter = conditions.value.log_filter
        }
      }
    }
  }

  dynamic "alert_strategy" {
    for_each = anytrue([for c in each.value.conditions : try(c.log_filter, null) != null]) ? [1] : []
    content {
      notification_rate_limit {
        period = "3600s"
      }
    }
  }
  depends_on = [google_monitoring_monitored_project.this, google_logging_metric.this]
}

resource "google_monitoring_dashboard" "this" {
  for_each       = { for d in var.dashboards : d.id => d }
  project        = module.scoping_projects[each.value.scope].project_id
  dashboard_json = each.value.json
}
