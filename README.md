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

## Cost controls
Budget alert (£20, credits excluded), BigQuery 30 GiB/day query quota,
free-tier region. See `docs/adr/0001-region-and-free-tier.md`.
