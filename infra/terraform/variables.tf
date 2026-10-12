variable "project_id" {
  description = "GCP project ID (from .env GCP_PROJECT_ID)"
  type        = string
}

variable "region" {
  description = "Region for all data resources. us-central1 = GCS always-free tier."
  type        = string
  default     = "us-central1"
}

variable "env" {
  description = "Environment name, used in labels"
  type        = string
  default     = "dev"
}

variable "developer_email" {
  description = "Your Google account. Gets permission to impersonate the service accounts (no key files)."
  type        = string

  validation {
    condition     = can(regex("@", var.developer_email))
    error_message = "developer_email must be an email address (run: gcloud config get-value account)."
  }
}

variable "deletion_protection" {
  description = "true = Terraform refuses to delete tables/buckets that contain data. false for a dev sandbox."
  type        = bool
  default     = false
}

variable "archive_retention_days" {
  description = "Processed landing files are kept in archive/ for this many days"
  type        = number
  default     = 90
}

variable "github_repository" {
  description = "owner/repo allowed to use Workload Identity Federation (Phase 9)"
  type        = string

  validation {
    condition     = can(regex("^[^/]+/[^/]+$", var.github_repository))
    error_message = "github_repository must look like owner/repo."
  }
}
