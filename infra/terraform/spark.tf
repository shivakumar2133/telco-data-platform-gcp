# Phase 13: Dataproc Serverless for Spark - run a PySpark batch without managing a cluster.
#
# Serverless Spark runs inside a VPC subnet that you own. It needs:
#   - Private Google Access, so workers without public IPs can reach BigQuery and GCS
#   - a firewall rule letting the Spark driver and executors talk to each other
# A dedicated small network keeps this separate from anything else in the project.
# VPC networks, subnets and firewall rules are free; you pay only while a batch runs.

resource "google_compute_network" "spark" {
  name                    = "spark-net"
  auto_create_subnetworks = false
  description             = "Dataproc Serverless batches (Phase 13)"

  depends_on = [google_project_service.apis]
}

resource "google_compute_subnetwork" "spark" {
  name                     = "spark-subnet"
  network                  = google_compute_network.spark.id
  region                   = var.region
  ip_cidr_range            = "10.10.0.0/24"
  private_ip_google_access = true
}

resource "google_compute_firewall" "spark_internal" {
  name          = "spark-allow-internal"
  network       = google_compute_network.spark.name
  description   = "Spark driver <-> executors inside spark-subnet only"
  direction     = "INGRESS"
  source_ranges = [google_compute_subnetwork.spark.ip_cidr_range]

  allow {
    protocol = "tcp"
  }
  allow {
    protocol = "udp"
  }
  allow {
    protocol = "icmp"
  }
}

# What the Spark job may do (it runs as sa-spark): read Bronze through the BigQuery
# Storage Read API, write the scratch dataset (Storage Write API), and run as a
# Dataproc worker. Dataset access is granted in bigquery.tf (bronze reader, scratch writer).
resource "google_project_iam_member" "spark" {
  for_each = toset([
    "roles/dataproc.worker",
    "roles/bigquery.readSessionUser",
  ])

  project = var.project_id
  role    = each.value
  member  = local.sa_member.spark

  depends_on = [google_service_account.sa]
}

# gcloud uploads the PySpark file to the lake bucket (dependencies/); the batch reads it
resource "google_storage_bucket_iam_member" "spark_code" {
  bucket = google_storage_bucket.lake.name
  role   = "roles/storage.objectViewer"
  member = local.sa_member.spark

  depends_on = [google_service_account.sa]
}

# You submit batches that run as sa-spark
resource "google_service_account_iam_member" "developer_acts_as_spark" {
  service_account_id = google_service_account.sa["spark"].name
  role               = "roles/iam.serviceAccountUser"
  member             = "user:${var.developer_email}"
}
