# APIs the platform needs. Already enabled in Phase 0; declaring them here
# means a brand-new project can be built from code alone.
locals {
  apis = [
    "bigquery.googleapis.com",
    "bigquerystorage.googleapis.com",
    "bigquerydatapolicy.googleapis.com",
    "datacatalog.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    "billingbudgets.googleapis.com",
    "pubsub.googleapis.com",
    # Phase 13: Dataproc Serverless (Spark) and the VPC subnet it runs in
    "dataproc.googleapis.com",
    "compute.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.apis)

  service            = each.value
  disable_on_destroy = false # never switch APIs off on destroy (provider 7.x default, made explicit)
}
