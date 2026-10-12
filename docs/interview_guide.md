# Interview guide

How to present this project in 60 seconds, 5 minutes, or a deep dive - and the questions it
usually triggers. All numbers come from the project itself (re-check with the `make verify*` targets).

## The 60-second pitch
> "I built an end-to-end data platform on Google Cloud for a synthetic telecom business. Seven
> sources - Oracle billing, SQL Server CRM, PostgreSQL inventory, call-record files, alarm exports,
> an SLA workbook and a ticketing API - land in a GCS lake and a BigQuery medallion architecture,
> incrementally, with watermark CDC. dbt builds a Kimball star schema with SCD2 history, and the
> headline use case is revenue assurance: rated calls against billed invoices.
> I injected 20 kinds of data defect into the sources and proved that my data-quality rules catch
> every one of them - 9,494 records, zero false positives - and that every row and every pound
> reconciles from source to dashboard. It's all Terraform, keyless security with policy tags and
> row-level security, CI/CD in GitHub Actions, and it runs inside the free tier."

## The 5-minute walk-through (follow one call record)
1. **Source**: a CDR in a daily CSV from "mediation". Some are duplicated, late, negative-duration,
   or on a cell the inventory doesn't know.
2. **Landing**: the file is validated against its contract; good files go to `raw/`, bad ones to
   `quarantine/`; an MD5 check stops the same file loading twice. Every load is in `ops.load_audit`.
3. **Bronze**: loaded as-is with lineage columns (`_run_id`, `_source_file`, `_ingested_at`),
   append-only, partitioned by ingestion day. Load jobs are free; streaming would not be.
4. **Silver**: dbt MERGE reads only rows newer than the table's high-water mark, de-duplicates with
   `QUALIFY ROW_NUMBER()`, types and flags defects (`is_late_arrival`, `dq_negative_duration`).
5. **Gold**: `fct_calls`, joined *as of call time* to the SCD2 customer and product versions;
   unknown cells point to an Unknown member (-1) instead of being dropped. Partitioned by call date,
   clustered by cell and customer - savings measured with real jobs (`make cost-compare`).
6. **Revenue assurance**: rated charges per subscription per month vs USAGE invoice lines - finds
   exactly the 127 leaked subscriptions (£350.73) and £40.91 on orphan subscriptions.
7. **Quality gate**: 24 rules, record-level quarantine, scorecard with tolerances, 48 reconciliation
   checks; an error-level breach stops `gold_ready`, so dashboards never refresh on bad data.
8. **Consumption**: a PII-free reporting layer feeds Looker Studio and Power BI with tested totals.

## Stories (STAR) worth telling
**1. A test that broke the pipeline for the wrong reason.** *Situation*: after adding Gold, the
Silver build started failing with "table not found". *Task*: keep layer-by-layer builds.
*Action*: found dbt's default *eager* indirect selection pulled Gold-vs-Silver reconciliation tests
into the Silver step; switched to `--indirect-selection buildable` in Makefile, DAG and CI, and added
a DAG test asserting it. *Result*: each test runs in the step that builds all its parents.

**2. 99.99% recall wasn't good enough.** One injected defect - an alarm with an unknown device - was
"missed". Investigation: the next day's re-export had a *corrected* device, so Silver (latest version)
was valid. I moved the rule to check every *delivered* version, because the source still sent bad data
once and its owner needs to know. Recall 100%, and I can explain current-state vs history checks.

**3. A platform constraint forced a redesign.** Dynamic data masking failed: it needs a Google Cloud
organization, and the project is personal. Kept policy tags for enforcement (raw PII denied to BI
identities) and published de-identified columns (hash, outward postcode, masked email) in Gold; the ADR
records how to switch back with an organization.

**4. Least privilege for CI.** Terraform plan needs to read everything, so the easy answer is the
Viewer role - which also reads every table, including raw PII in Bronze. I gave the CI identity
metadata-only roles instead ("sees the shape of everything, the data of nothing"), plans with
`-lock=false`, and only `main` can act as the production identity through Workload Identity Federation.

**5. Proving the DQ claims instead of asserting them.** The generator logs every injected defect id;
`make dq-report` compares them with the quarantine table record by record and fails CI-style if
recall < 100%. It even accounts for defects that were quarantined at ingestion (a rejected file).

## Likely questions - short answers
| Question | Answer |
|---|---|
| Why medallion? | Separation of concerns: Bronze is replayable raw history, Silver is clean current state + history, Gold is shaped for use. Any layer can be rebuilt from the one below. |
| How is incremental CDC done? | Watermark on `updated_at` per table, child tables via parent watermark, at-least-once with idempotent MERGE; the watermark moves only after the load is verified. |
| Deletes at source? | Not captured by watermarks - needs log-based CDC (Datastream) or periodic full-key comparison; snapshots use `hard_deletes: invalidate`. |
| SCD2 how? | dbt snapshots (timestamp strategy); facts join the version valid at event time; first version valid from 1900 so early facts still match. |
| Partitioning vs clustering? | Partition prunes whole days (big, predictable filter); clustering sorts within partitions for selective filters/joins. Measured with real jobs, not estimates. |
| How do you control BigQuery cost? | Partition filters, incremental models, `maximum_bytes_billed`, a daily quota, a budget alert, job labels per dbt model for attribution. |
| How do you test a pipeline? | Unit tests (pytest), dbt schema/singular tests, reconciliation tests (counts and sums), DQ rules with tolerances, DAG integrity tests, policy-as-tests for CI. |
| How do you handle bad data? | Don't drop it: quarantine files, flag rows, unknown members in dims, record-level failure table, tolerance per rule, error rules stop publication. |
| Why Airflow *and* GitHub Actions? | Airflow schedules data (time, dependencies, retries, backfills); Actions ships code (tests, plan, deploy). Different jobs. |
| Secrets? | Secret Manager, values pushed outside Terraform so they never enter state; no SA keys - impersonation locally, WIF in CI. |
| PII? | Policy tags enforce column access; BI reads de-identified columns; row access policies by region; a test stops PII entering the reporting layer. |
| What breaks first at 100x? | `fct_calls` merges (already incremental + partitioned); the laptop sources/Airflow (move to Cloud Composer or a managed scheduler); file ingestion (move to event-driven Cloud Run). |
| What would you do differently in production? | Log-based CDC (Datastream), Composer, an organization for dynamic masking, Dataplex for catalog/DQ at scale, SLO-based freshness alerts. |

## Numbers to remember
1.13M CDRs/month · 7 sources · 54 dbt models · 150+ dbt tests · 24 DQ rules · 9,494 defects, 100% recall,
0 false positives · 48 reconciliation checks · leakage 127 subs / £350.73 · 5 service accounts, 0 keys ·
free-tier cost.

## Bridge to your current role
If your day job already involves reconciling data across source systems in BigQuery, say so: this
project shows the same skill with the engineering around it - ingestion, modelling, orchestration,
testing, security and deployment - which is the step from analyst to data engineer. (Don't name
client systems or share client details in a public repo or an interview.)
