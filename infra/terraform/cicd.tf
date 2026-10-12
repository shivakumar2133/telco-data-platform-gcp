# Phase 9: GitHub Actions -> Google Cloud without any key.
#
# Workload Identity Federation: GitHub signs a short-lived OIDC token for each job
# ("I am workflow X in repo Y on ref Z"). Google checks the signature and the
# conditions below, then lets the job act as a service account for up to an hour.
# Nothing to rotate, nothing to leak. Oracle analogy: Kerberos/external authentication
# instead of a password stored in a wallet.
#
#   pull requests -> sa-cicd       (metadata read-only: terraform plan)
#   main branch   -> sa-transform  (dbt build of the real Silver/Gold/DQ layers)
#   terraform apply stays a human step: CI only plans.

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions"
  description               = "OIDC tokens from GitHub Actions for ${var.github_repository}"

  depends_on = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"

  # Claims from the GitHub token that IAM bindings can refer to
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
    "attribute.is_main"    = "assertion.ref == 'refs/heads/main' ? 'true' : 'false'"
  }

  # Reject tokens from every other repository before any binding is even evaluated
  attribute_condition = "assertion.repository == '${var.github_repository}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

locals {
  wif_principal_set = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}"
}

# Any workflow in the repo (pull requests included) may act as sa-cicd ...
resource "google_service_account_iam_member" "cicd_from_github" {
  service_account_id = google_service_account.sa["cicd"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "${local.wif_principal_set}/attribute.repository/${var.github_repository}"
}

# ... but only code that is already on main may act as sa-transform (production writes)
resource "google_service_account_iam_member" "transform_from_main" {
  service_account_id = google_service_account.sa["transform"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "${local.wif_principal_set}/attribute.is_main/true"
}

# ---------------------------------------------------------------- what sa-cicd may do
# terraform plan refreshes every resource, so it must READ their configuration and IAM
# policies - but not the data. Basic roles/viewer would also read every table (including
# raw PII in Bronze) and is deliberately NOT used. "Sees the shape of everything, the
# data of nothing." If a plan fails with a 403, the error names the missing permission.
resource "google_project_iam_member" "cicd_metadata_read" {
  for_each = toset([
    "roles/browser",                         # project metadata (number, labels)
    "roles/bigquery.metadataViewer",         # datasets/tables, no table data
    "roles/iam.securityReviewer",            # getIamPolicy on everything
    "roles/iam.roleViewer",                  # the custom dbt governance role
    "roles/iam.serviceAccountViewer",        # service accounts
    "roles/iam.workloadIdentityPoolViewer",  # this pool and provider
    "roles/secretmanager.viewer",            # secret metadata, never the values
    "roles/serviceusage.serviceUsageViewer", # enabled APIs
    "roles/datacatalog.viewer",              # policy tag taxonomy
  ])

  project = var.project_id
  role    = each.value
  member  = local.sa_member.cicd

  depends_on = [google_service_account.sa]
}

# Bucket settings (lifecycle, versioning) for the plan; lists object names, can't read them
resource "google_storage_bucket_iam_member" "cicd_lake_metadata" {
  bucket = google_storage_bucket.lake.name
  role   = "roles/storage.legacyBucketReader"
  member = local.sa_member.cicd

  depends_on = [google_service_account.sa]
}

# Read the Terraform state (plan runs with -lock=false, so no write access is needed)
resource "google_storage_bucket_iam_member" "cicd_state_reader" {
  bucket = "${var.project_id}-tfstate"
  role   = "roles/storage.objectViewer"
  member = local.sa_member.cicd

  depends_on = [google_service_account.sa]
}
