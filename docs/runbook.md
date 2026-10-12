# Runbook

What to do when something alerts. Start every investigation with the pipeline health view:

```sql
select * from `<project>.ops.rpt_pipeline_health` order by freshness_status desc;
```

## Pipeline: BigQuery job failed
*Cloud Monitoring email. A job run by `sa-ingest` or `sa-transform` ended with an error.*

1. BigQuery console -> **Job history** -> *Project history*, filter **User = sa-transform** (or
   sa-ingest), status **Failed**. The error message names the cause.
2. Common causes:
   | Error | Meaning | Action |
   |---|---|---|
   | `Query exceeded limit for bytes billed` | a model scanned > 2 GB | missing partition filter; check the model's `where`, or `is_incremental()` |
   | `Quota exceeded: ... query usage per day` | 30 GiB/day project cap | wait for reset (midnight Pacific) or find the runaway job in `make cost-report` |
   | `Access Denied ... policy tags` | a model selects a tagged column without permission | was the SA's Fine-Grained Reader removed? `make tf-plan` |
   | `Not found: Table ...` | upstream table missing | run the upstream step; check Airflow |
   | `error('alert drill...')` | `make alert-drill` | nothing - the drill worked |
3. Fix, then re-run the failed step only (Airflow: *Clear* the task; locally: `make dbt-build`).
4. The alert closes itself after 24 h, or close it in Monitoring -> Incidents.

## Security: repeated access denied
*Cloud Monitoring email. One identity was refused BigQuery access more than twice in 10 minutes.*

1. Logs Explorer:
   ```
   resource.type="bigquery_project"
   (protoPayload.status.code=7 OR protoPayload.metadata.jobChange.job.jobStatus.errorResult.code=7)
   ```
   The `principalEmail` says who; the message says which table or policy tag.
2. Expected: `make verify8` tests denials on purpose (sa-analyst, sa-reporting).
3. Unexpected: a person or service account probing PII or other regions. Check what they tried,
   whether it was a misconfigured dashboard, and if not, disable the identity
   (`gcloud iam service-accounts disable ...`) and investigate.

## Airflow task failed (chat webhook)
1. Open the task log from the link in the message.
2. Ingestion tasks are idempotent: watermarks only move after a verified load, so *Clear* and
   re-run is always safe.
3. `reconcile_bronze` and `dbt_build_dq` have no retries on purpose: a mismatch needs a person.
   Read `ops.recon_results` / `ops.rpt_dq_latest` before re-running.

## DQ gate failed (`dbt_build_dq` red, `gold_ready` not published)
1. `select * from ops.rpt_dq_latest where status = 'BREACHED'` - which rule, how far over tolerance.
2. `select record_key, record_json from ops.dq_failures where rule_id = '<rule>' and
   detected_date = current_date()` - the actual records (data stewards only: PII).
3. Source problem: tell the source owner, then either fix at source and re-run, or (business
   decision) raise the rule's tolerance in `transform/macros/dq_rules.sql` via a PR.

## Reconciliation FAIL
1. `select * from ops.rpt_recon_latest where status = 'FAIL'`.
2. `source_to_bronze` only: a source write between extraction and capture - re-run ingestion
   and `make dq-capture`; it clears on the next run.
3. `bronze_to_silver` / `silver_to_gold`: a code change lost or duplicated rows - revert the last
   dbt change (`git revert`, CI deploys it) and investigate the join.

## Source is LATE / STALE (pipeline health)
- Laptop pipeline: start the sources and Airflow (`make sources-up airflow-up`) - expected after
  days off. In production this would be a page.
- One object only: check its last `ops.load_audit` row (`error_message`), then the source itself.

## dbt: `412 Precondition check failed` / `did not meet condition IF_MATCH`
Two builds updated the same table at the same moment (for example `make dbt-build` on a laptop
while GitHub's Deploy dbt was running). BigQuery rejects the second update; nothing is corrupted.
1. `gh run list --workflow deploy-dbt.yml --limit 2` and check Airflow for a running `telco_transform`.
2. Wait for the other build, then re-run once. Never run two production builds at once:
   production is built by Airflow or by Deploy dbt; personal experiments belong in a dev dataset.

## Budget alert
1. `make cost-report` - which identity and which dbt model.
2. Usual suspect: a full refresh of `fct_calls` or a dashboard on DirectQuery. Fix, then check the
   next day's report.
