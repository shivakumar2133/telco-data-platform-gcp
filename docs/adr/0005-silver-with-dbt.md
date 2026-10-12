# ADR 0005: Silver layer with dbt - staging views, incremental MERGE, snapshots

**Status:** Accepted

## Context
Bronze is append-only and holds every extracted version, with file/API data as text.
Analysts need one clean, typed, current row per business key, plus history for
slowly changing entities, at low query cost.

## Decisions
1. **dbt Core 1.12 on BigQuery**, run as `sa-transform` by impersonation (no keys).
   Dataform was the GCP-native alternative; dbt was chosen for portability and
   because it is the most requested transformation tool in job descriptions.
2. **Two model layers in the `silver` dataset:**
   - `stg_*` **views**: rename, cast (`SAFE_CAST`), standardise, add `dq_*` flags.
     One row per Bronze row. No storage cost.
   - entity tables (`crm_customers`, `usage_cdrs`, ...) **incremental MERGE** on the
     business key. Each run reads only Bronze rows with `_ingested_at` newer than the
     table's maximum, keeps the latest version per key (`QUALIFY ROW_NUMBER()`), and merges.
3. **Partitioning and clustering where queries filter:** CDRs and alarms by day of the
   event (late arrivals land in the right partition), invoices and tickets by month,
   clustering on the join/filter keys.
4. **SCD Type 2 with dbt snapshots** for customers, subscriptions and products
   (timestamp strategy on `updated_at`; open rows end at 9999-12-31).
5. **Tests prove the logic**: unique/not_null keys (dedup works), `keys_match_source`
   (every Bronze key reaches Silver), accepted values (standardisation works).
   Known source defects are `severity: warn` - reported, never silently dropped.
6. **Cost guards**: `maximum_bytes_billed` (2 GB) per query in the profile; staging
   as views; incremental reads.
7. **Data-aware orchestration**: `telco_transform` runs when ingestion publishes
   `bronze_ready`, and publishes `silver_ready` for Gold (Phase 6).

## Consequences
- `dbt build --full-refresh` rebuilds Silver from Bronze at any time (Bronze is the system of record).
- Snapshots record history from their first run; earlier history exists only in Bronze.
- Hard deletes at source are still not detected (see ADR 0003).
