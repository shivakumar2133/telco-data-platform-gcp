# Looker Studio: build guide (about 1-2 hours)

Looker Studio is free and reads BigQuery directly. You build in the browser; nothing to install.

## 1. Data sources (once)
1. Open <https://lookerstudio.google.com> -> **Create -> Data source -> BigQuery**.
2. **My projects** -> your project (`telco-dp-...`) -> dataset **gold** -> table **rpt_kpi_monthly** -> **Connect**.
3. Top right, **Data credentials: Owner's credentials** (default). Viewers see the data through your
   access; that is safe here because reporting tables contain no personal data.
4. **Data freshness**: 12 hours (the pipeline runs daily; this keeps BigQuery costs at zero).
5. Check field types: `month` = Date (Year Month), money fields = Currency (GBP), counts = Number.
6. Repeat for `rpt_revenue_assurance`, `rpt_network_daily`, `rpt_sla_performance`,
   `rpt_customer_base`, and in dataset **ops**: `rpt_dq_latest`, `rpt_recon_latest`.

### Calculated fields (add in the data source, so every chart uses the same definition)
| Data source | Field | Formula | Type |
|---|---|---|---|
| rpt_kpi_monthly | Drop rate | `SUM(dropped_calls) / SUM(call_attempts)` | Percent |
| rpt_kpi_monthly | SLA breach % | `SUM(breached_tickets) / SUM(measured_tickets)` | Percent |
| rpt_kpi_monthly | Leakage % of usage | `SUM(unbilled_usage) / SUM(rated_usage)` | Percent |
| rpt_network_daily | Drop rate | `SUM(dropped_calls) / SUM(call_attempts)` | Percent |
| rpt_network_daily | Failure rate | `SUM(failed_calls) / SUM(call_attempts)` | Percent |
| rpt_sla_performance | SLA breach % | `SUM(breached_tickets) / SUM(measured_tickets)` | Percent |
| rpt_sla_performance | Avg resolution (h) | `SUM(total_resolution_hours) / SUM(measured_tickets)` | Number |
| rpt_revenue_assurance | Is leakage | `assurance_status IN ("LEAKAGE", "UNBILLED_NO_ACCOUNT")` | Boolean |

Always divide **sums**: `AVG(drop_rate)` would give a quiet day the same weight as a busy one.

## 2. Report layout
**Create -> Report**, add the data sources, then **Theme and layout**: a simple light theme,
canvas 1366 x 768, one accent colour. Add a header bar on every page: title, the date-range
control and a "Data as of" text box.

### Page 1 - Executive (rpt_kpi_monthly)
- 6 scorecards: Billed revenue `SUM(billed_revenue)`, Rated usage, Unbilled usage,
  Leakage subscriptions, Drop rate, SLA breach % (with "compare to previous period").
- Time series: `month` x billed_revenue (bars) and rated_usage (line, right axis).
- Note text: "CDR feed covers September 2026 only; July-August are billing-only."

### Page 2 - Revenue assurance (rpt_revenue_assurance)
- Controls: drop-down `customer_segment`, `region`, `product_type`.
- Bar chart: `assurance_status` x `SUM(variance_amount)`, sorted descending.
- Table with heatmap: `region` x `product_name`, metrics subscriptions, rated_amount,
  billed_amount, variance_amount; filter **Is leakage = true**.
- Scorecards: leaked £, subscriptions affected.
- Text: how leakage is defined (rated usage with no USAGE invoice line).

### Page 3 - Network quality (rpt_network_daily)
- Time series: `call_date` x Drop rate, breakdown `technology`.
- Bar chart: `region` x Drop rate (sorted), reference line at the network average.
- Pivot table: rows `region`, columns `technology`, metric Drop rate, heatmap colouring.
- Scorecards: call attempts, voice minutes, data GB.

### Page 4 - SLA performance (rpt_sla_performance)
- Bar chart: `priority` x SLA breach %, and Avg resolution (h) as a second metric.
- Stacked bar: `category` x tickets, breakdown `service_level`.
- Time series: `opened_month` x tickets, open_tickets.
- Scorecard: tickets_missing_resolution_time (a data-quality issue the business should see).

### Page 5 - Data quality (ops.rpt_dq_latest, ops.rpt_recon_latest)
- Scorecards (filtered): rules CLEAN, TOLERATED, BREACHED (`COUNT(rule_id)` with a filter on `status`).
- Table: rule_id, dimension, severity, failed_records, failed_pct, max_failure_pct, status,
  with conditional formatting: BREACHED red, TOLERATED amber, CLEAN green.
- Table from rpt_recon_latest: check_type, entity, measure, expected, actual, status.
- Text: "Every number on the other pages is reconciled source -> Bronze -> Silver -> Gold."

## 3. Share
**Share -> Manage access -> Anyone with the link can view** (no PII, owner's credentials).
Copy the link into `transform/models/exposures.yml` (`url:`) and into the main README.
**File -> Download -> PDF** for an offline copy, and screenshots into `dashboards/screenshots/`.

## Cost check
Each chart runs one query on a table of a few hundred rows: BigQuery bills the 10 MB minimum
per query, ~1,000 dashboard refreshes per month stay far inside the 1 TB free tier.
In BigQuery -> Job history you will see the queries Looker Studio runs; that is also how you
debug a chart that shows unexpected numbers.
