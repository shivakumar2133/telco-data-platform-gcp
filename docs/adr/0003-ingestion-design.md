# ADR 0003: Ingestion design - watermark CDC, schema contracts, append-only Bronze

**Status:** Accepted

## Context
Three databases, three file types and one REST API must land in BigQuery Bronze
reliably, cheaply, and in a way that can be reconciled back to each source.

## Decisions

1. **CDC by watermark, not log-based CDC.** Incremental objects are extracted with
   `WHERE updated_at > :last_watermark` (bind variable). Tables without their own
   timestamp (`invoice_lines`) use the **parent's** timestamp ("child" mode).
   Managed log-based CDC (Datastream, GoldenGate) would also capture hard deletes,
   but has a running cost; deletes are out of scope until Silver adds key-snapshot
   comparison.
2. **Watermark moves only after a verified load.** Order: extract, write Parquet,
   load Bronze, compare counts, *then* store the new watermark. A failure anywhere
   means the next run re-reads the same rows: **at-least-once** delivery.
   Duplicates are expected in Bronze and removed in Silver.
3. **Schema contract from the source catalogue.** Column types come from the
   database's own metadata (SQLAlchemy inspector, like ALL_TAB_COLUMNS), not from
   the data. An all-NULL batch therefore keeps its declared type and never breaks
   the Bronze table. Files and API payloads land as STRING; Silver casts them.
4. **Bronze is append-only, partitioned by `_ingested_at`**, with lineage columns
   (`_run_id`, `_source_system`, `_source_object`, `_source_file`, `_ingested_at`).
   New source columns are added automatically (`ALLOW_FIELD_ADDITION`).
5. **File-level contracts.** A file that breaks its contract (wrong header, header
   `record_count` != records, unreadable) is quarantined whole. Row-level problems
   are kept and handled in Silver. Re-delivered identical files (same MD5) are skipped.
6. **Every run is audited** in `ops.load_audit`: source count, extracted count,
   loaded count, checksum, watermark range, status. A count mismatch fails the load.
7. **Metadata is written with load jobs** (free), not DML or streaming inserts.
   Watermarks are append-only; the current value is the latest row per object.

## Consequences
- Re-running any command is safe (idempotent for files, at-least-once for tables).
- Hard deletes in sources are not yet detected (documented gap).
- The same code runs offline (`--local`) for tests and demos.
