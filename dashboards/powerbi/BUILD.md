# Power BI: build guide (about 2 hours, Windows)

Power BI Desktop is free (Microsoft Store or <https://powerbi.microsoft.com/desktop>).
It runs on Windows, so use it there, not in WSL.

## 1. Connect (Import mode)
1. **Home -> Manage Parameters -> New parameter**: name `ProjectId`, type Text, value = your
   project id (`GCP_PROJECT_ID` in `.env`).
2. **Home -> Get data -> Google BigQuery -> Connect -> Sign in** with your Google account.
3. Close the navigator, open **Transform data**, and create the queries in
   [`queries.pq`](queries.pq): **New Source -> Blank Query -> Advanced Editor**, paste one block,
   rename the query (`BigQueryTable`, `kpi_monthly`, ...). Create `BigQueryTable` first.
4. **Close & Apply**. Import mode copies a few thousand rows into the file: the report is
   instant, and BigQuery is queried only on refresh.

Why Import, not DirectQuery: the reporting tables are tiny and refresh daily, so Import gives
the fastest visuals and the lowest BigQuery cost. DirectQuery would send a query per visual
per click.

Identity: Desktop signs in as you. Reporting tables contain no personal data, so the file is
safe to share whoever refreshes it. (In production, refresh would run in the Power BI service
under a dedicated identity; Google's connector supports a service-account key, which this
project deliberately avoids.)

## 2. Model (Model view)
1. **Months** table: **Modeling -> New table**
   ```DAX
   Months = DISTINCT ( SELECTCOLUMNS ( dim_date, "month_start", dim_date[month_start],
                                       "year_month", dim_date[year_month] ) )
   ```
   Mark **dim_date** (not Months) as the date table: **Table tools -> Mark as date table ->
   date_day**. Months has one row per month, which Power BI's date-table check rejects.
2. Relationships (single direction, many-to-one):

   | From (many) | To (one) |
   |---|---|
   | `network_daily[date_key]` | `dim_date[date_key]` |
   | `kpi_monthly[month]` | `Months[month_start]` |
   | `revenue_assurance[usage_month]` | `Months[month_start]` |
   | `sla_performance[opened_month]` | `Months[month_start]` |
   | `dim_date[month_start]` | `Months[month_start]` |

   Result: a small star - a shared date dimension filters every fact table the same way.
3. Hide technical columns (`date_key`, `*_month` on fact tables) so report builders use the
   date tables. Set Format: currency fields `£#,0.00`, percentages `0.0%`.
4. Measures: create a `_Measures` table and add the measures in [`measures.dax`](measures.dax).

## 3. Report pages
Same five pages as Looker Studio (see `../looker_studio/BUILD.md`), using the measures:
1. **Executive**: cards (Billed Revenue, Billed Revenue MoM %, Unbilled Usage, Leakage % of Usage,
   Drop Rate, SLA Breach %), clustered column + line `Months[year_month]`.
2. **Revenue assurance**: slicers (segment, region, product type), bar of Variance Amount by
   assurance_status, matrix region x product with Leaked Amount, decomposition tree on
   Leaked Amount (region -> product_type -> customer_segment) - interviewers like this one.
3. **Network**: line Drop Rate by `dim_date[date_day]` and technology; bar Drop Rate vs Network
   by region with conditional colours (red above zero).
4. **SLA**: bar SLA Breach % and Avg Resolution Hours by priority; stacked Tickets by category.
5. **Data quality**: cards Rules Clean / Rules Breached; table of `dq_latest` with
   conditional formatting on status.

## 4. Save and commit
- Save as `dashboards/powerbi/telco_operations.pbit` (**File -> Export -> Power BI template**):
  a template holds the model, measures and visuals but **no data**, so it is small and safe for git.
- Export each page as PNG into `dashboards/screenshots/` (`powerbi_01_executive.png`, ...).
- Optional: **Publish** to your Power BI workspace and put the link in `exposures.yml`.

## Check the numbers
`make verify11` prints the KPIs from BigQuery. Card values in Power BI must match exactly
(Billed Revenue for September, Unbilled Usage, Drop Rate). If they don't, the usual causes are
a relationship in the wrong direction or a measure that averages a rate.
