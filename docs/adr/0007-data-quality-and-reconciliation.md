# ADR 0007: Data quality rules and cross-layer reconciliation

**Status:** Accepted

## Context
Phases 5-6 test that our *transformations* are correct (dbt tests). The business also needs
to know whether the *data* is fit for use: how many customers lack an email, how much
usage was never billed, and proof that nothing was lost between source and dashboard.
20 kinds of defect were injected in Phase 1 and logged in `defects_manifest.json`, so
detection can be measured, not assumed.

## Decisions
1. **Rules as data, in one macro** (`macros/dq_rules.sql`). Each rule has an id, dimension,
   severity, tolerance (`max_failure_pct`), the relation it checks, a record key and a failure
   condition. Three models are generated from it, so a new rule is one dict:
   - `ops.dq_rule_catalog` - what is checked and why (for humans and dashboards)
   - `ops.dq_failures` - **record-level** failures with the full record as JSON (the
     quarantine/exception table; "which 50 customers?", not just "50")
   - `ops.dq_scorecard` - population, failures, % and status per rule per run
   Considered: dbt tests with `store_failures` (no population, no history, one table per test),
   Great Expectations / Dataplex (another tool or service to run and pay for). Revisit Dataplex
   data quality scans if rules must be managed outside dbt.
2. **Severity + tolerance instead of pass/fail.** Real data always has some defects. A rule is
   CLEAN, TOLERATED (within agreed %), or BREACHED. A breached `error` rule fails the build;
   a breached `warn` rule alerts. Invariants that must never happen have tolerance 0.
3. **Check where the defect is visible**: duplicates and re-exports in Bronze (Silver has
   already de-duplicated them), referential problems in Gold (unknown members), SLA workbook
   issues in the latest Bronze file. An alarm re-exported with a *corrected* device is still
   reported, because the source sent bad data once.
4. **Reconciliation is persisted, not just tested** (`ops.recon_results`): source -> Bronze
   (counts captured from the sources by `quality/capture_source_totals.py`), audit -> Bronze,
   file headers, Bronze -> Silver, Silver -> Gold (rows and money), source -> Silver money,
   to the penny. The expected side comes from the source, never from our own pipeline.
5. **Append-only history with `full_refresh: false`**, partitioned by run date, 90-day
   expiry on record-level failures. A `--full-refresh` can never erase audit evidence.
6. **Quality gate before publishing.** `dbt_build_dq` runs after Gold and owns the
   `gold_ready` asset: consumers are only told about data that passed (circuit breaker).
7. **The framework is checked too**: scorecard failures must equal distinct keys in
   `dq_failures`, and `quality/dq_report.py` compares every flagged key with the manifest
   (recall and precision), exiting non-zero if any injected defect was missed.

## Consequences
- Detection is measured: 100% of 9,494 injected defects are caught (4 of them earlier, by
  quarantining the rejected alarm export), with zero false positives.
- Each run scans the checked tables once more (~100-200 MB at this scale, free tier).
- Control totals are captured just after extraction, so a source write in between shows as
  a FAIL that clears on the next run. Production fix: read totals AS OF the extraction
  snapshot (Oracle flashback `AS OF SCN`, SQL Server snapshot isolation).
