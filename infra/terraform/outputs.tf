output "lake_bucket" {
  value = google_storage_bucket.lake.name
}

output "datasets" {
  value = { for k, m in module.datasets : k => m.dataset_id }
}

output "service_accounts" {
  value = { for k, sa in google_service_account.sa : k => sa.email }
}

output "secrets" {
  value = [for s in google_secret_manager_secret.s : s.secret_id]
}
