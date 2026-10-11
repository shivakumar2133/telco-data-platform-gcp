provider "google" {
  project = var.project_id
  region  = var.region

  # Every resource that supports labels gets these (cost reports can group by them)
  default_labels = {
    project    = "telco-data-platform"
    env        = var.env
    managed_by = "terraform"
  }
}
