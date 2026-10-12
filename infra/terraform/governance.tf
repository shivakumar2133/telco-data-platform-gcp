# Phase 8: column-level security with policy tags.
#
# A TAXONOMY is a classification scheme; its POLICY TAGS are attached to columns
# (by dbt, see transform/models/**/_*.yml). Once a column is tagged:
#   Fine-Grained Reader -> can select it   (sa-transform, the data steward)
#   anyone else         -> "Access Denied" on that column, even project owners
# BI identities read de-identified copies built in Gold (email_masked, msisdn_masked,
# customer_name_hash, postcode_area) - see the note on data masking below.
# Oracle analogy: column-level VPD / column masking, driven by a classification label.
# Display names allow only letters, numbers, spaces, - and _ (no brackets).

locals {
  pii_tags = {
    email      = "Email address"
    phone      = "Phone number - MSISDN"
    name       = "Name or street address"
    birth_date = "Date of birth"
    postcode   = "Customer postcode"
    raw_record = "Raw record copy - DQ quarantine"
  }

  pii_readers = [local.sa_member.transform, "user:${var.developer_email}"]
}

resource "google_data_catalog_taxonomy" "pii" {
  display_name           = "telco-pii"
  description            = "Personal data classification. Enforced: tagged columns need Fine-Grained Reader."
  region                 = var.region # must match the datasets' location
  activated_policy_types = ["FINE_GRAINED_ACCESS_CONTROL"]

  depends_on = [google_project_service.apis]
}

resource "google_data_catalog_policy_tag" "pii_root" {
  taxonomy     = google_data_catalog_taxonomy.pii.id
  display_name = "PII"
  description  = "Personally identifiable information. Access is granted on this root tag."
}

resource "google_data_catalog_policy_tag" "pii" {
  for_each = local.pii_tags

  taxonomy          = google_data_catalog_taxonomy.pii.id
  parent_policy_tag = google_data_catalog_policy_tag.pii_root.id
  display_name      = each.value
  description       = "Personal data: ${each.value}. Readable only with Fine-Grained Reader."
}

# Granted on the ROOT tag, so it applies to every child tag (hierarchy)
resource "google_data_catalog_policy_tag_iam_member" "pii_readers" {
  for_each = toset(local.pii_readers)

  policy_tag = google_data_catalog_policy_tag.pii_root.name
  role       = "roles/datacatalog.categoryFineGrainedReader"
  member     = each.value

  depends_on = [google_service_account.sa]
}

# Dynamic data masking (google_bigquery_datapolicy_data_policy + Masked Reader) needs the
# project to belong to a Google Cloud ORGANIZATION. This project has none (personal
# account), so masking is done in Gold instead: masked copies of PII columns
# (email_masked, msisdn_masked, ...). The tags still ENFORCE column-level security:
# without Fine-Grained Reader, selecting a raw PII column returns Access Denied.
# With an organization, add a data policy per tag (see docs/adr/0008) and drop the copies.

# ---------------------------------------------------------------- dbt's governance rights
# dbt (sa-transform) re-applies policy tags, row access policies and table grants on
# every run, because CREATE OR REPLACE TABLE drops them. Those need permissions that
# only BigQuery Data Owner has - but Data Owner could also change dataset IAM.
# A custom role grants exactly what is needed, on the datasets dbt writes.
resource "google_project_iam_custom_role" "dbt_governance" {
  role_id     = "telcoDbtGovernance"
  title       = "Telco dbt governance"
  description = "Attach policy tags, manage row access policies and table grants on tables dbt builds"
  permissions = [
    "bigquery.tables.setCategory",
    "bigquery.tables.getIamPolicy",
    "bigquery.tables.setIamPolicy",
    "bigquery.rowAccessPolicies.create",
    "bigquery.rowAccessPolicies.update",
    "bigquery.rowAccessPolicies.delete",
    "bigquery.rowAccessPolicies.list",
    "bigquery.rowAccessPolicies.getIamPolicy",
    "bigquery.rowAccessPolicies.setIamPolicy",
  ]
}

resource "google_bigquery_dataset_iam_member" "transform_governance" {
  for_each = toset(["silver", "gold", "ops"])

  dataset_id = module.datasets[each.key].dataset_id
  role       = google_project_iam_custom_role.dbt_governance.id
  member     = local.sa_member.transform

  depends_on = [google_service_account.sa]
}

# Attaching a tag requires reading the taxonomy
resource "google_project_iam_member" "transform_taxonomy_viewer" {
  project = var.project_id
  role    = "roles/datacatalog.viewer"
  member  = local.sa_member.transform

  depends_on = [google_service_account.sa]
}
