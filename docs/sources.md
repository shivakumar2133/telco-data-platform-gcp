# Source systems

All data is synthetic (Faker + NumPy, seed 42). No real customer or operator data is used.

| Source | Technology | Simulates | Tables / files | Extract pattern (Phase 3) |
|---|---|---|---|---|
| CRM | SQL Server 2022 | Customer relationship mgmt | customers, products, subscriptions | Incremental on `updated_at` |
| Billing | Oracle Free 23ai | Billing system | billing_accounts, invoices, invoice_lines, payments | Incremental on `updated_at` / `created_at`, full for lines of changed invoices |
| Network inventory | PostgreSQL 16 | Inventory DB | sites, cells, devices | Incremental on `updated_at` |
| CDRs | CSV, one file per day | Mediation platform | cdr_YYYYMMDD.csv (~37k rows/day) | New-file detection |
| Alarms | Nested JSON, one per day | Network management system | alarms_YYYYMMDD.json | New-file detection, flatten nested JSON |
| SLA targets | XLSX | Business-owned spreadsheet | sla_targets.xlsx | Full reload on change |
| Tickets | REST API (FastAPI) | ServiceNow-style SaaS | /api/v1/tickets | Paginated, `updated_since` watermark |

## Cross-system keys

```
CRM.customers.customer_id ──< CRM.subscriptions.customer_id
CRM.customers.customer_id ──  Billing.billing_accounts.customer_id
CRM.subscriptions.subscription_id ──< Billing.invoice_lines.subscription_id
CRM.subscriptions.msisdn ──< CDR.msisdn_a
Inventory.cells.cell_id ──< CDR.cell_id
Inventory.devices.device_id ──< Alarms.device.device_id
Alarms.alarm_id ──< Tickets.alarm_id
CRM.customers.customer_id ──< Tickets.customer_id
SLA (service_level, priority) ──< Tickets (service_level, priority)
```

There are no foreign keys across systems, which is why reconciliation is needed.

## Injected defects

Every defect is recorded in `data_generator/output/defects_manifest.json` with the affected IDs.
Phase 7 must detect each one.

| Defect | Where | What the pipeline should do |
|---|---|---|
| crm_duplicate_customer | CRM | Match on normalised email + DOB, flag duplicate |
| crm_null_email | CRM | DQ warning, keep row |
| crm_invalid_postcode | CRM | DQ warning, keep row |
| crm_orphan_subscription | CRM | Referential check fails; usage is unbilled |
| billing_revenue_leakage | Billing | Rated CDR usage vs billed USAGE lines: gap must equal leakage + orphan usage |
| billing_header_line_mismatch | Billing | invoices.total_amount vs SUM(lines) |
| cdr_duplicate | CDR files | Deduplicate on cdr_id |
| cdr_late_arrival | CDR files | Partition by start_time, not by file date |
| cdr_unknown_cell | CDR files | Referential check vs inventory |
| cdr_negative_duration | CDR files | Quarantine row |
| alarm_cleared_before_raised | Alarms | Quarantine row |
| alarm_unknown_device | Alarms | Referential check vs inventory |
| alarm_reexported | Alarms | Deduplicate on alarm_id |
| alarm_record_count_mismatch | Alarms | Header control total != records: fail the file |
| ticket_resolved_without_date | Tickets | DQ failure |
| ticket_unknown_customer | Tickets | Referential check vs CRM |
| sla_* (4 defects) | SLA workbook | Trim, cast, normalise %, deduplicate |
