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

## Security model
| Service account | Lake bucket | bronze | silver | gold | ops | secrets |
|---|---|---|---|---|---|---|
| sa-ingest | read/write | write | - | - | write | read |
| sa-transform | read | read | write | write | write | - |
| sa-reporting | - | - | - | read | read | - |

No service-account keys: developers impersonate, CI uses Workload Identity Federation.
Least privilege is tested by `make verify2`. See `docs/adr/0002-iam-secrets-keyless.md`.

## Cost controls
Budget alert (£20, credits excluded), BigQuery 30 GiB/day query quota,
free-tier region. See `docs/adr/0001-region-and-free-tier.md`.
