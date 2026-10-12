# Phase 8: column-level security (policy tags + dynamic data masking).
#
# A TAXONOMY is a classification scheme; its POLICY TAGS are attached to columns
# (by dbt, see transform/models/**/_*.yml). Once a column is tagged:
#   Fine-Grained Reader  -> sees the real value      (sa-transform, the data steward)
#   Masked Reader        -> sees the masking rule's output (sa-reporting, sa-analyst)
#   neither              -> "Access Denied" on that column, even project owners
# Oracle analogy: Oracle Data Redaction (DBMS_REDACT) policies, but the policy
# follows a classification label instead of being written per table.

locals {
  # tag key => masking rule applied for Masked Readers
  pii_tags = {
    email      = { display = "Email address", masking = "EMAIL_MASK" }               # XXXXX@example.com
    phone      = { display = "Phone number (MSISDN)", masking = "LAST_FOUR_CHARACTERS" } # XXXXX1053
    name       = { display = "Name or street address", masking = "SHA256" }           # joinable hash
    birth_date = { display = "Date of birth", masking = "DATE_YEAR_MASK" }             # 1984-01-01
    postcode   = { display = "Customer postcode", masking = "FIRST_FOUR_CHARACTERS" }  # SW1AXXXXX
    raw_record = { display = "Raw record copy (DQ quarantine)", masking = "ALWAYS_NULL" }
  }

  masked_readers = [local.sa_member.reporting, local.sa_member.analyst]
  pii_readers    = [local.sa_member.transform, "user:${var.developer_email}"]
}

resource "google_data_catalog_taxonomy" "pii" {
  display_name           = "telco-pii"
  description            = "Personal data classification. Enforced: tagged columns need Fine-Grained or Masked Reader."
  region                 = var.region # must match the datasets' location
  activated_policy_types = ["FINE_GRAINED_ACCESS_CONTROL"]

  depends_on = [google_project_service.apis]
}

resource "google_data_catalog_policy_tag" "pii_root" {
  taxonomy     = google_data_catalog_taxonomy.pii.id
  display_name = "PII"
  description  = "Personally identifiable information. Child tags define how each kind is masked."
}

resource "google_data_catalog_policy_tag" "pii" {
  for_each = local.pii_tags

  taxonomy          = google_data_catalog_taxonomy.pii.id
  parent_policy_tag = google_data_catalog_policy_tag.pii_root.id
  display_name      = each.value.display
  description       = "Masked for Masked Readers with ${each.value.masking}"
}

# Granted on the ROOT tag, so it applies to every child tag (hierarchy)
resource "google_data_catalog_policy_tag_iam_member" "pii_readers" {
  for_each = toset(local.pii_readers)

  policy_tag = google_data_catalog_policy_tag.pii_root.name
  role       = "roles/datacatalog.categoryFineGrainedReader"
  member     = each.value

  depends_on = [google_service_account.sa]
}

resource "google_bigquery_datapolicy_data_policy" "mask" {
  for_each = local.pii_tags

  location         = var.region
  data_policy_id   = "mask_${each.key}"
  policy_tag       = google_data_catalog_policy_tag.pii[each.key].name
  data_policy_type = "DATA_MASKING_POLICY"

  data_masking_policy {
    predefined_expression = each.value.masking
  }
}

resource "google_bigquery_datapolicy_data_policy_iam_member" "masked_readers" {
  for_each = {
    for pair in setproduct(keys(local.pii_tags), local.masked_readers) :
    "${pair[0]}|${pair[1]}" => { tag = pair[0], member = pair[1] }
  }

  location       = var.region
  data_policy_id = google_bigquery_datapolicy_data_policy.mask[each.value.tag].data_policy_id
  role           = "roles/bigquerydatapolicy.maskedReader"
  member         = each.value.member

  depends_on = [google_service_account.sa]
}

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
