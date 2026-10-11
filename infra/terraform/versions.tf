terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0" # latest 7.x; 8.0 (Oct 2026) is a breaking release - upgrade deliberately
    }
  }

  # Remote state in the bucket created in Phase 0.
  # Bucket/prefix are passed at init time: make tf-init
  backend "gcs" {}
}
