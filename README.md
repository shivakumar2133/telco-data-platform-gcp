# Telco Data Platform on GCP

End-to-end data engineering platform on **synthetic telecom data** (customers,
billing, CDRs, network faults, tickets, SLAs): Oracle, SQL Server, PostgreSQL,
files and a REST API → GCS/BigQuery medallion → dbt star schema → Looker Studio & Power BI.

Headline use case: **revenue assurance and SLA performance**, reconciling rated
call records against billed invoices, and fault-to-ticket resolution against SLA targets.

## Stack
Python · SQL · BigQuery · GCS · Airflow · dbt · Terraform · Docker · GitHub Actions · Pub/Sub

## Status
- [x] Phase 0: Foundations (env, GCP project, cost guardrails, repo skeleton)
- [x] Phase 1: Synthetic data with injected defects + Oracle / SQL Server / PostgreSQL / REST API sources
- [x] Phase 2: Terraform - lake bucket, medallion datasets, least-privilege service accounts, Secret Manager
- [x] Phase 3: Ingestion to Bronze - full + incremental (watermark CDC), files with quarantine, paginated API with retries, audit trail
- [x] Phase 4: Orchestration - Airflow 3.3 (Docker), 3 DAGs, retries, webhook alerts, backfill by logical date
- [x] Phase 5: Silver with dbt 1.12 - staging views, incremental MERGE, SCD2 snapshots, 59 tests, asset-triggered DAG
- [x] Phase 6: Gold star schema - 7 dimensions (SCD2 as-of joins, unknown members), 5 facts, revenue-assurance mart, measured partition/cluster savings
- [x] Phase 7: Data quality + reconciliation - 24 rules with tolerances, record-level quarantine, scorecard, source-to-Gold reconciliation, 100% of injected defects detected
- [x] Phase 8: Governance - PII policy tags (column-level security), de-identified BI columns, row-level security by region, custom least-privilege role for dbt

## Source systems
| System | Tech | Data |
|---|---|---|
| CRM | SQL Server 2022 | customers, products, subscriptions |
| Billing | Oracle 23ai Free | accounts, invoices, invoice lines, payments |
| Network inventory | PostgreSQL 16 | sites, cells, devices |
| Mediation | CSV files | ~1.1M call detail records / month |
| Network management | Nested JSON | alarm exports |
| Service management | XLSX | SLA targets |
| Ticketing | REST API (FastAPI) | trouble tickets, paginated |

20 kinds of data defect are deliberately injected and logged, so later phases can prove
the data quality checks catch them. See [docs/sources.md](docs/sources.md).

## Quick start
    cp .env.example .env   # set GCP_PROJECT_ID
    make setup
    make test
    make check             # Phase 0 checks
    make phase1            # generate data, start sources, load, verify
    make tf-init tf-plan tf-apply secrets-push verify2   # GCP infrastructure
    make drop-files ingest verify3                       # sources -> Bronze
    make ingest-local                                    # same pipeline offline, no GCP
    make airflow-env airflow-build airflow-up            # Airflow UI on http://localhost:8080
    make dbt-debug dbt-build                             # Bronze -> Silver -> Gold
    make cost-compare                                    # measured partitioning savings
    make dq-capture dq-build verify7                     # DQ rules, reconciliation, defect report
    make governance-env dbt-build verify8                # policy tags, masking, row-level security

## Ingestion (Bronze)
| Source | Pattern | Bronze table |
|---|---|---|
| Oracle / SQL Server / PostgreSQL | full, incremental on `updated_at`, child-of-parent | `bronze.<system>__<table>` |
| CDR CSV, alarm JSON, SLA XLSX | landing/ -> validate -> raw/ (or quarantine/) -> archive/ | `bronze.files__<object>` |
| Tickets REST API | paginated, `updated_since` watermark, retry on 429/5xx | `bronze.api__tickets` |

Every load is recorded in `ops.load_audit` (source vs loaded counts, checksum, watermark range).
Design decisions: `docs/adr/0003-ingestion-design.md`.

## Orchestration (Airflow 3.3)
| DAG | Schedule | What it does |
|---|---|---|
| `telco_ingest_daily` | 02:00 UTC | 3 databases in parallel (max 2 at once) -> reconciliation gate -> `bronze_ready` asset |
| `telco_tickets_hourly` | :15 every hour | Incremental tickets from the REST API |
| `telco_files_daily` | per business day | Deliver that day's CDR + alarm files -> validate -> Bronze. Backfillable |

Tasks retry twice with exponential backoff and alert a chat webhook on final failure.
Design decisions: `docs/adr/0004-orchestration.md`.

## Silver layer (dbt)
`stg_*` views clean and type every Bronze row; entity tables (`crm_customers`, `billing_invoices`,
`usage_cdrs`, ...) are **incremental MERGEs** that read only new Bronze rows and keep the latest
version per key. Customers, subscriptions and products have **SCD Type 2** snapshots.
Tests prove de-duplication, reconciliation to Bronze and standardisation; injected source
defects surface as warnings. Design: `docs/adr/0005-silver-with-dbt.md`.

## Gold layer (star schema)
`fct_calls`, `fct_invoice_lines`, `fct_invoices`, `fct_tickets`, `fct_network_faults` with
`dim_customer` / `dim_product` (SCD2, as-of joins), `dim_subscription`, `dim_cell`, `dim_device`,
`dim_sla`, `dim_date`. Diagram and grain: [docs/data_model.md](docs/data_model.md).

**Revenue assurance** (`mart_revenue_assurance`) compares rated CDR charges with billed usage per
subscription: it finds exactly the injected leakage (127 subscriptions, £350.73) plus £40.91 of
usage on orphan subscriptions that can never be billed.

## Data quality and reconciliation
24 rules defined once in `transform/macros/dq_rules.sql` generate three tables in `ops`:
`dq_rule_catalog` (what is checked), `dq_failures` (every failing record, as JSON) and
`dq_scorecard` (population, % failed, tolerance, CLEAN / TOLERATED / BREACHED per run).
An ERROR rule above tolerance stops the pipeline before `gold_ready` is published.

`recon_results` proves rows and money survive every hop: source -> Bronze -> Silver -> Gold,
using control totals read from the source databases (`quality/capture_source_totals.py`).

Detection is measured against the 20 injected defect types (`make dq-report`):

| Result | Records |
|---|---:|
| Injected defects | 9,494 |
| Flagged by a DQ rule (exact record) | 9,490 |
| Quarantined at ingestion (rejected alarm export) | 4 |
| Missed | 0 |
| False positives | 0 |

Design: `docs/adr/0007-data-quality-and-reconciliation.md`.

## Security model
| Service account | Lake bucket | bronze | silver | gold | ops | secrets | personal data |
|---|---|---|---|---|---|---|---|
| sa-ingest | read/write | write | - | - | write | read | - |
| sa-transform | read | read | write | write | write | - | real values |
| sa-reporting | - | - | - | read | read | - | de-identified copies only |
| sa-analyst | - | - | - | 3 tables, North West rows only | - | - | de-identified copies only |

**Column-level security:** PII columns carry policy tags (`telco-pii` taxonomy): only the
pipeline and the data steward can select `email`; BI identities get Access Denied and use
`email_masked` (`XXXXX@example.com`), `msisdn_masked`, `customer_name_hash`, `postcode_area`.
(Dynamic masking needs a Google Cloud organization; this project is personal - see the ADR.)
**Row-level security:** row access policies by region, re-applied by dbt on every build.
Design: `docs/adr/0008-governance-column-and-row-security.md`.

No service-account keys: developers impersonate, CI uses Workload Identity Federation.
Least privilege is tested by `make verify2`. See `docs/adr/0002-iam-secrets-keyless.md`.

## Cost controls
Budget alert (£20, credits excluded), BigQuery 30 GiB/day query quota,
free-tier region. See `docs/adr/0001-region-and-free-tier.md`.
