# Reusable module: a BigQuery dataset plus its reader/writer grants.
# Oracle analogy: CREATE USER <schema> + GRANT SELECT/INSERT on it, in one unit.

variable "dataset_id" {
  type = string
}

variable "description" {
  type = string
}

variable "location" {
  type = string
}

variable "default_table_expiration_days" {
  description = "null = tables never expire"
  type        = number
  default     = null
}

variable "delete_contents_on_destroy" {
  type    = bool
  default = false
}

variable "readers" {
  description = "IAM members granted roles/bigquery.dataViewer"
  type        = list(string)
  default     = []
}

variable "writers" {
  description = "IAM members granted roles/bigquery.dataEditor"
  type        = list(string)
  default     = []
}

variable "layer" {
  description = "Medallion layer label"
  type        = string
}

resource "google_bigquery_dataset" "this" {
  dataset_id                 = var.dataset_id
  description                = var.description
  location                   = var.location
  delete_contents_on_destroy = var.delete_contents_on_destroy
  default_table_expiration_ms = (
    var.default_table_expiration_days == null ? null : var.default_table_expiration_days * 86400000
  )

  labels = {
    layer = var.layer
  }
}

resource "google_bigquery_dataset_iam_member" "readers" {
  for_each = toset(var.readers)

  dataset_id = google_bigquery_dataset.this.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = each.value
}

resource "google_bigquery_dataset_iam_member" "writers" {
  for_each = toset(var.writers)

  dataset_id = google_bigquery_dataset.this.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = each.value
}

output "dataset_id" {
  value = google_bigquery_dataset.this.dataset_id
}
