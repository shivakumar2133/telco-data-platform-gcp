# Medallion datasets. All in the same region as the lake bucket
# (a load job from GCS into BigQuery fails if the locations differ).
locals {
  datasets = {
    bronze = {
      layer       = "bronze"
      description = "Raw data as received, append-only, plus load metadata"
      expiry_days = null
      readers     = [local.sa_member.transform]
      writers     = [local.sa_member.ingest]
    }
    silver = {
      layer       = "silver"
      description = "Cleaned, typed, deduplicated, CDC-merged, SCD2 history"
      expiry_days = null
      readers     = []
      writers     = [local.sa_member.transform]
    }
    gold = {
      layer       = "gold"
      description = "Star schema for reporting: facts and dimensions"
      expiry_days = null
      readers     = [local.sa_member.reporting]
      writers     = [local.sa_member.transform]
    }
    ops = {
      layer       = "ops"
      description = "Pipeline metadata: load audit, watermarks, DQ and reconciliation results"
      expiry_days = null
      readers     = [local.sa_member.reporting]
      writers     = [local.sa_member.ingest, local.sa_member.transform]
    }
    scratch = {
      layer       = "scratch"
      description = "Ad-hoc work. Tables auto-delete after 7 days (cost control)"
      expiry_days = 7
      readers     = []
      writers     = []
    }
  }
}

module "datasets" {
  source   = "./modules/bq_dataset"
  for_each = local.datasets

  dataset_id                    = each.key
  layer                         = each.value.layer
  description                   = each.value.description
  location                      = var.region
  default_table_expiration_days = each.value.expiry_days
  delete_contents_on_destroy    = !var.deletion_protection
  readers                       = each.value.readers
  writers                       = each.value.writers

  depends_on = [google_service_account.sa, google_project_service.apis]
}

# ---- Ops tables used from Phase 3 onwards

resource "google_bigquery_table" "load_audit" {
  dataset_id          = module.datasets["ops"].dataset_id
  table_id            = "load_audit"
  description         = "One row per extract/load run: counts, checksums, watermarks, status"
  deletion_protection = var.deletion_protection
  schema              = file("${path.module}/schemas/load_audit.json")

  time_partitioning {
    type  = "DAY"
    field = "started_at"
  }
  clustering = ["source_system", "object_name", "status"]
}

resource "google_bigquery_table" "watermarks" {
  dataset_id          = module.datasets["ops"].dataset_id
  table_id            = "watermarks"
  description         = "High-water mark per source object for incremental extraction"
  deletion_protection = var.deletion_protection
  schema              = file("${path.module}/schemas/watermarks.json")
}

# Phase 7: control totals read straight from the source databases after extraction.
# The independent "expected" side of reconciliation (written by sa-ingest, read by dbt).
resource "google_bigquery_table" "source_control_totals" {
  dataset_id          = module.datasets["ops"].dataset_id
  table_id            = "source_control_totals"
  description         = "Row counts and money totals per source table, captured after each extraction"
  deletion_protection = var.deletion_protection
  schema              = file("${path.module}/schemas/source_control_totals.json")

  time_partitioning {
    type  = "DAY"
    field = "captured_at"
  }
  clustering = ["source_system", "object_name"]
}
