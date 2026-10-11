# ADR 0002: Least-privilege IAM, keyless auth, secrets outside Terraform state

**Status:** Accepted

## Context
Pipelines need credentials for GCP and for three source databases plus an API.
Downloaded service-account JSON keys are the most common way GCP credentials leak.
Terraform state stores every attribute in plain text, including secret values.

## Decision
1. **One service account per job role**: `sa-ingest`, `sa-transform`, `sa-reporting`.
   Access is granted at dataset / bucket / secret level, not project level.
   Only `roles/bigquery.jobUser` is project-wide (needed to run any query).
2. **No key files.** Developers impersonate service accounts
   (`roles/iam.serviceAccountTokenCreator`), receiving 1-hour tokens.
   CI will use Workload Identity Federation (Phase 9).
3. **Secrets**: Terraform creates the Secret Manager containers and IAM;
   values are pushed with `gcloud` from stdin, so they never enter state or shell history.
   Secrets are replicated only in the data region.
4. **Least privilege is tested**, not assumed: `scripts/verify_phase2.py` checks
   that each SA can do its job and is denied everything else.

## Consequences
- A leaked SA token expires within an hour; there is no long-lived key to revoke.
- Adding a new pipeline role means a new SA plus explicit grants (slightly more work, by design).
- Power BI may need a key for its BigQuery connector (Phase 11); that will be
  documented as a scoped, rotated exception for `sa-reporting` only.
