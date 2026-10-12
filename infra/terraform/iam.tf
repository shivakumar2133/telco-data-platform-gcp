# One service account per job role (least privilege). No key files are ever created:
# you (developer_email) impersonate them, and CI uses Workload Identity Federation (Phase 9).
#
#             lake bucket    bronze   silver   gold    ops      secrets
#   ingest    read/write     write    -        -       write    read
#   transform read           read     write    write   write    -
#   reporting -              -        -        read    read     -
#   analyst   -              -        -        3 tables, North West rows only, PII masked
locals {
  service_accounts = {
    ingest    = "Extracts sources, lands files in GCS, loads Bronze"
    transform = "Runs dbt: Bronze -> Silver -> Gold"
    reporting = "Read-only access to Gold for dashboards (Looker Studio, Power BI)"
    analyst   = "Regional analyst: row-level security demo (one region, masked PII)"
  }

  # Built from strings (not resource attributes) so they are known at plan time
  sa_member = {
    for k, _ in local.service_accounts :
    k => "serviceAccount:sa-${k}@${var.project_id}.iam.gserviceaccount.com"
  }
}

resource "google_service_account" "sa" {
  for_each = local.service_accounts

  account_id   = "sa-${each.key}"
  display_name = "sa-${each.key}"
  description  = each.value

  depends_on = [google_project_service.apis]
}

# Every SA may run BigQuery jobs (queries/loads) billed to this project.
# Dataset-level roles (bigquery.tf) decide WHAT data each can touch.
resource "google_project_iam_member" "bq_job_user" {
  for_each = google_service_account.sa

  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = each.value.member
}

resource "google_storage_bucket_iam_member" "ingest_lake" {
  bucket = google_storage_bucket.lake.name
  role   = "roles/storage.objectAdmin" # create, read, delete (move landing -> archive)
  member = google_service_account.sa["ingest"].member
}

resource "google_storage_bucket_iam_member" "transform_lake" {
  bucket = google_storage_bucket.lake.name
  role   = "roles/storage.objectViewer"
  member = google_service_account.sa["transform"].member
}

# Let the developer act as each SA (short-lived tokens instead of JSON keys)
resource "google_service_account_iam_member" "developer_can_impersonate" {
  for_each = google_service_account.sa

  service_account_id = each.value.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "user:${var.developer_email}"
}
