# ADR 0012: Spark (Dataproc Serverless) vs SQL (dbt on BigQuery)

**Status:** Accepted - dbt stays the default; Spark kept as a measured comparison

## Context
Job adverts ask for Spark. The platform transforms everything in BigQuery SQL with dbt. To
choose with evidence rather than habit, one slice - CDRs to cell-day network quality
(`mart_cell_daily`) - was rebuilt in PySpark, straight from Bronze, and run both locally and on
Dataproc Serverless.

## What was built
- `spark/cell_daily.py`: type the all-STRING CDRs, de-duplicate by `cdr_id`, current cell/site
  versions, broadcast join, aggregate per day x cell. Pure functions, unit-tested on tiny
  DataFrames (`tests/spark`, also in CI).
- Runs locally on the Parquet lake (`make spark-local`) or on Dataproc Serverless runtime 2.3
  (Spark 3.5) reading Bronze through the BigQuery Storage Read API and writing
  `scratch.spark_cell_daily` through the Storage Write API (`make spark-submit`).
- `make spark-compare` reconciles Spark with dbt per day and region and prints what each cost.

## Results
- **Identical numbers**: 390 day x region groups, 1,132,336 call attempts, 23,135 dropped calls -
  every count equal to dbt, minutes and GB equal within per-cell rounding.
- Local Spark on a laptop: ~30 s for 1.13M rows.
- Cost per run: dbt's BigQuery jobs for this slice bill a few hundred MB (free tier); a Serverless
  batch with a 4-core driver and 2 x 4-core executors uses roughly 12 DCUs for a few minutes,
  ~1 DCU-hour at $0.06 (pennies), and is never inside the free tier. Exact figures:
  `make spark-compare` (dbt job labels + `approximateUsage` of the latest batch).

## Decision
**SQL/dbt by default; Spark when the work is not a good fit for SQL:**

| Use dbt / BigQuery SQL when | Use Spark when |
|---|---|
| Data already in BigQuery, set-based logic (joins, aggregates, windows) | Data lives outside the warehouse (files, Kafka, other clouds) and should be processed before loading |
| Analysts must read and change the logic | Logic needs a programming language: ML features, complex parsing, graph or iterative algorithms, Python libraries |
| Cost should scale to zero with no infrastructure | Volumes or shapes where slot-based SQL gets expensive and dedicated compute is cheaper |
| Testing = dbt tests + reconciliation | Unit tests on DataFrames, fine control over partitioning / joins |

## Consequences
- One code path for production (dbt); the Spark slice is a maintained, tested comparison - not a
  second source of truth. Its output lives in `scratch` (expires in 7 days).
- Spark needed a VPC subnet with Private Google Access, a firewall rule and a dedicated service
  account (`sa-spark`: reads Bronze, writes scratch only) - infrastructure SQL never needed.
- Apache Beam / Dataflow would be the choice for a unified batch + streaming pipeline (Phase 10).
