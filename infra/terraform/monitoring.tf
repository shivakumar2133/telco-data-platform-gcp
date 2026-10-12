# Phase 12: alerting on what the cloud can see.
#
# The pipeline already alerts from inside (Airflow webhook on task failure, dbt tests,
# DQ/reconciliation gate). These alerts come from OUTSIDE the pipeline - BigQuery's own
# audit logs - so they still fire if Airflow is down or a job is run by hand:
#   1. a BigQuery job run by a pipeline identity failed (SQL error, quota, byte cap)
#   2. repeated "access denied" on BigQuery (someone probing data they may not read)
# BigQuery audit logs are on by default and cost nothing; the two log-based metrics are
# far inside the 150 MiB/month free allotment; alert policies are not charged before
# September 2027 (Cloud Observability pricing).
# Oracle analogy: an alert on ORA- errors in the alert log / AUD$ failed-access rows,
# raised by Enterprise Manager rather than by the batch job itself.

resource "google_monitoring_notification_channel" "email" {
  display_name = "Data platform alerts (email)"
  type         = "email"

  labels = {
    email_address = var.developer_email
  }

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------- 1. pipeline job failures
resource "google_logging_metric" "pipeline_job_errors" {
  name        = "bq_pipeline_job_errors"
  description = "BigQuery jobs that finished with an error, run by sa-ingest or sa-transform"
  filter      = <<-EOT
    resource.type="bigquery_project"
    protoPayload.metadata.jobChange.after="DONE"
    protoPayload.metadata.jobChange.job.jobStatus.errorResult.code:*
    protoPayload.authenticationInfo.principalEmail=~"^sa-(ingest|transform)@"
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "principal"
      value_type  = "STRING"
      description = "Service account that ran the job"
    }
  }
  label_extractors = {
    principal = "EXTRACT(protoPayload.authenticationInfo.principalEmail)"
  }
}

resource "google_monitoring_alert_policy" "pipeline_job_errors" {
  display_name = "Pipeline: BigQuery job failed"
  combiner     = "OR"

  conditions {
    display_name = "sa-ingest / sa-transform job errors > 0 (5 min)"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.pipeline_job_errors.name}\" AND resource.type=\"bigquery_project\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["metric.label.principal"]
      }
      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close = "86400s"
  }
  notification_channels = [google_monitoring_notification_channel.email.id]

  documentation {
    mime_type = "text/markdown"
    content   = "A BigQuery job run by the pipeline failed. Runbook: docs/runbook.md, section 'Pipeline: BigQuery job failed'. Find it: BigQuery console -> Job history, filter by the service account."
  }
}

# ---------------------------------------------------------------- 2. access denied (security)
resource "google_logging_metric" "access_denied" {
  name        = "bq_access_denied"
  description = "BigQuery requests rejected with PERMISSION_DENIED (incl. policy-tag and row-policy denials)"
  filter      = <<-EOT
    resource.type="bigquery_project"
    (protoPayload.status.code=7 OR protoPayload.metadata.jobChange.job.jobStatus.errorResult.code=7)
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "principal"
      value_type  = "STRING"
      description = "Who was denied"
    }
  }
  label_extractors = {
    principal = "EXTRACT(protoPayload.authenticationInfo.principalEmail)"
  }
}

resource "google_monitoring_alert_policy" "access_denied" {
  display_name = "Security: repeated BigQuery access denied"
  combiner     = "OR"

  conditions {
    display_name = "More than 2 denials by one identity in 10 minutes"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.access_denied.name}\" AND resource.type=\"bigquery_project\""
      comparison      = "COMPARISON_GT"
      threshold_value = 2
      duration        = "0s"
      aggregations {
        alignment_period     = "600s"
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["metric.label.principal"]
      }
      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close = "86400s"
  }
  notification_channels = [google_monitoring_notification_channel.email.id]

  documentation {
    mime_type = "text/markdown"
    content   = "An identity was refused BigQuery access repeatedly (often policy tags or row access policies). Expected once while running `make verify8` (it tests the denials on purpose). Runbook: docs/runbook.md, section 'Security: repeated access denied'."
  }
}
