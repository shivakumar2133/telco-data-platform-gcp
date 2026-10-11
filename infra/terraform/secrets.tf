# Terraform creates the secret CONTAINERS and their access rules only.
# Secret VALUES are added by `make secrets-push` (gcloud), so they never
# appear in Terraform state, which is stored in plain text.
locals {
  secrets = {
    "oracle-etl-reader-password"   = "Oracle billing DB, read-only etl_reader"
    "mssql-etl-reader-password"    = "SQL Server CRM DB, read-only etl_reader"
    "postgres-etl-reader-password" = "PostgreSQL inventory DB, read-only etl_reader"
    "tickets-api-key"              = "Ticketing REST API key"
  }
}

resource "google_secret_manager_secret" "s" {
  for_each = local.secrets

  secret_id = each.key
  annotations = {
    description = each.value
  }

  # Keep secret data in the same region as the data (residency), not "global"
  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.apis]
}

# Secret-level grant (not project-level): sa-ingest can read only these secrets
resource "google_secret_manager_secret_iam_member" "ingest_reads" {
  for_each = google_secret_manager_secret.s

  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.sa["ingest"].member
}
