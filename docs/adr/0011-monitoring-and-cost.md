# ADR 0011: Monitoring, alerting and cost attribution

**Status:** Accepted

## Context
Failures were already caught *inside* the pipeline (Airflow alerts, dbt tests, the DQ gate). That
misses failures when the orchestrator itself is down, jobs run outside Airflow (CI, people), and
security events. Cost was controlled by guards but not attributed.

## Decisions
1. **Alert from the platform's own audit logs.** BigQuery writes an audit entry for every job,
   free and on by default. Two log-based metrics feed two Cloud Monitoring alert policies (email):
   - failed jobs run by `sa-ingest`/`sa-transform` (SQL errors, quota, byte cap, permissions);
   - more than 2 PERMISSION_DENIED in 10 minutes by one identity (PII or region probing).
   Both fire whoever or whatever ran the job.
2. **No freshness alert in Cloud Monitoring.** The pipeline runs from a laptop, so an absence alert
   would fire after every day off. Freshness is a view (`ops.rpt_pipeline_health`, thresholds
   matching `dbt source freshness`) on the dashboards; with a 24/7 orchestrator it would become a
   metric-absence alert.
3. **Every alert has a runbook entry** (`docs/runbook.md`), linked from the alert's documentation.
4. **Alerting is tested**: `make alert-drill` runs a deliberately failing job as `sa-transform`.
5. **Cost attribution by job labels.** dbt labels each BigQuery job with the model or test that ran
   it (`query-comment: job-label: true`); `make cost-report` groups INFORMATION_SCHEMA job history
   by identity and by dbt model. Guards stay: per-query byte cap, daily quota, budget alert.

## Consequences
- Cost: audit logs free; two user-defined log metrics use bytes of the 150 MiB/month free
  allotment; alert policies are not charged before September 2027 (then about $0.35 per metric
  reference per month).
- Alert emails during `make verify8` are expected (it tests denials on purpose).
- Production next steps: chat/PagerDuty channels, SLO on freshness, error-budget reporting.
