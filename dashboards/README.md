# Dashboards

Two BI tools on the same governed tables, so the numbers match everywhere:

| Tool | Good at | Guide |
|---|---|---|
| Looker Studio | free, browser-based, native BigQuery, share with a link | [looker_studio/BUILD.md](looker_studio/BUILD.md) |
| Power BI Desktop | semantic model, DAX measures, what most UK enterprises (including telcos) use | [powerbi/BUILD.md](powerbi/BUILD.md) |

## What the dashboards read
Only the **reporting layer**: small, aggregated tables built by dbt (`transform/models/gold/reporting`).

| Table | Grain | Used for |
|---|---|---|
| `gold.rpt_kpi_monthly` | month | executive scorecards and trends |
| `gold.rpt_revenue_assurance` | month x status x segment x region x product | leakage analysis |
| `gold.rpt_network_daily` | day x region x technology | drop rate, traffic |
| `gold.rpt_sla_performance` | month x priority x service level x category | SLA breach %, resolution time |
| `gold.rpt_customer_base` | region x segment x status | customer counts |
| `ops.rpt_dq_latest`, `ops.rpt_recon_latest` | rule / check | data quality page |

Why a separate layer instead of pointing BI at the star schema:
1. **No personal data, by construction.** Reporting tables never select a policy-tagged column
   (a unit test enforces it), so `SELECT *` works for `sa-reporting` and a shared dashboard
   cannot leak PII, whoever's credentials it runs with.
2. **Additive measures only.** Ratios (drop rate, breach %, leakage %) are calculated in the BI
   tool from sums. Averaging daily rates would weight a quiet day like a busy one.
3. **Tested totals.** Each table is reconciled to the model it summarises (`column_sum_matches`),
   so the dashboard's revenue *is* the ledger's revenue.
4. **Cheap and fast.** The largest table is ~1,000 rows: every dashboard query costs the
   10 MB BigQuery minimum (free tier), and no BI Engine reservation is needed.
5. **Lineage.** `transform/models/exposures.yml` registers both dashboards in dbt, so
   `make dbt-docs` shows which dashboards a model change affects.

## Headline numbers to expect (synthetic data, September 2026)
| KPI | Value |
|---|---|
| Billed revenue (Sep invoices) | £585,080.31 |
| Rated usage | £17,907.37 |
| Unbilled usage (leakage + no account) | £391.64 (127 + 15 subscriptions) |
| Call attempts | 1,132,336 |
| SLA breach % (resolved tickets) | ~17-20% by priority |

Run `make verify11` to print yours; the dashboards must show the same figures.

## Screenshots
Save one PNG per page in `screenshots/` (e.g. `looker_01_executive.png`) and link them from
the main README: reviewers look at pictures before they read code.
