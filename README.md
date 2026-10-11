# Telco Data Platform on GCP

End-to-end data engineering platform on **synthetic telecom data** (customers,
billing, CDRs, network faults, tickets, SLAs): Oracle, SQL Server, PostgreSQL,
files and a REST API → GCS/BigQuery medallion → dbt star schema → Looker Studio & Power BI.

## Stack
Python · SQL · BigQuery · GCS · Airflow · dbt · Terraform · Docker · GitHub Actions · Pub/Sub

## Status
- [x] Phase 0: Foundations (env, GCP project, cost guardrails, repo skeleton)

## Quick start
    cp .env.example .env   # set GCP_PROJECT_ID
    make setup
    make test
    make check

## Cost controls
Budget alert (£20, credits excluded), BigQuery 30 GiB/day query quota,
free-tier region. See `docs/adr/0001-region-and-free-tier.md`.
