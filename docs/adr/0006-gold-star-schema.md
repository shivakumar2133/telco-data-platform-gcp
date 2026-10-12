# ADR 0006: Gold layer as a Kimball star schema

**Status:** Accepted

## Context
BI tools (Looker Studio, Power BI) and analysts need simple, fast, consistent models:
revenue by customer segment, dropped-call rates by region, SLA performance, and the
revenue-assurance comparison of rated vs billed usage.

## Decisions
1. **Kimball star schema**: facts at the lowest useful grain (one CDR, one invoice line,
   one ticket, one alarm) surrounded by conformed dimensions. Dimensions are
   **denormalised** (cell + site in one table) - BigQuery storage is cheap, joins are not.
   One Big Table was considered; a star keeps dimensions reusable across facts and SCD2 clean.
2. **Integer surrogate keys** via `FARM_FINGERPRINT` of the natural key (+ `valid_from` for
   SCD2). Deterministic, so a full rebuild produces identical keys.
3. **SCD Type 2 as-of joins**: a fact joins the dimension version valid at the event time
   (`event_ts >= valid_from AND event_ts < valid_to`). The first version is valid from
   1900-01-01 so history before the first snapshot still resolves.
4. **Unknown members (`-1`)** in every dimension. Orphan subscriptions, unknown cells and
   unknown customers keep their facts; the problem is visible (`dq_*` flags,
   `customer_sk = -1`) instead of revenue silently disappearing in an inner join.
5. **Partition by event date, cluster by the common filters/join keys.** Measured with
   `make cost-compare` (real jobs, not estimates).
6. **`fct_calls` is incremental** (MERGE on `cdr_id`, reading only newly merged Silver
   rows); smaller facts and marts are rebuilt in full each run (cheap and simpler).
7. **Reconciliation is part of the build**: counts and money in Gold must equal Silver
   (`keys_match_source`, `column_sum_matches`), so a join fan-out fails the pipeline.

## Consequences
- Gold is read by `sa-reporting` only; BI tools never touch Bronze or Silver.
- Revenue-assurance results are reproducible and traceable to individual CDRs and invoice lines.
