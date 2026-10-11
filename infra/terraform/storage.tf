# Data lake bucket (Bronze landing zone). One bucket, separated by prefix:
#   landing/     files dropped by "source systems" (CDR CSV, alarm JSON, SLA XLSX) - like an SFTP inbox
#   raw/         immutable Bronze copies: raw/<source>/<object>/dt=YYYY-MM-DD/*.parquet
#   archive/     landing files after successful processing (auto-deleted after N days)
#   quarantine/  files rejected by validation, kept for investigation
#   tmp/         scratch space, auto-deleted after 7 days
resource "google_storage_bucket" "lake" {
  name     = "${var.project_id}-lake"
  location = upper(var.region)

  storage_class               = "STANDARD" # only STANDARD is covered by the free tier
  uniform_bucket_level_access = true       # IAM only, no per-object ACLs
  public_access_prevention    = "enforced" # can never be made public
  force_destroy               = !var.deletion_protection

  versioning {
    enabled = false # raw/ is write-once by design; versions would double storage
  }

  # GCS keeps deleted objects for 7 days by default (and bills for them). Off for a sandbox.
  soft_delete_policy {
    retention_duration_seconds = 0
  }

  lifecycle_rule {
    condition {
      age            = 7
      matches_prefix = ["tmp/"]
    }
    action {
      type = "Delete"
    }
  }

  lifecycle_rule {
    condition {
      age            = var.archive_retention_days
      matches_prefix = ["archive/"]
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.apis]
}
