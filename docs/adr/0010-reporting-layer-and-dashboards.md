# ADR 0010: Reporting layer and dashboards

**Status:** Accepted

## Context
Gold is a star schema for analysts. Dashboards have different needs: they are shared widely,
refreshed often, and built by people who should not have to know about SCD2 joins,
column-level security or which measures are additive.

## Decisions
1. **A reporting layer (`rpt_*`) between Gold and every BI tool**, built by dbt like the rest:
   KPI per month, revenue assurance, network daily, SLA performance, customer base, plus the
   latest DQ and reconciliation results. BI tools read nothing else.
2. **No personal data, enforced by a test.** Reporting models may not reference any PII column;
   so `SELECT *` works for `sa-reporting` (no column-level denials), and a dashboard shared with
   a link, running on its owner's credentials, cannot expose personal data.
3. **Additive measures only; ratios in the BI tool from sums.** A stored daily drop rate,
   averaged over a month, weights a quiet day like a busy one. Both BI guides define the same
   ratio formulas, so Looker Studio and Power BI show identical numbers.
4. **Every reporting total is reconciled** to its source model (`column_sum_matches`): the
   dashboard revenue equals the invoice-line ledger, the dashboard call count equals the CDR fact.
5. **Two tools, one definition.** Looker Studio (free, native BigQuery, link sharing) and Power BI
   (semantic model + DAX, the enterprise standard) read the same tables. Power BI uses Import mode:
   tables are tiny and refreshed daily, so it is faster and cheaper than DirectQuery.
6. **dbt exposures** register both dashboards; lineage shows which dashboards a model change affects.

## Consequences
- Dashboard queries hit tables of a few hundred rows: each costs the 10 MB minimum, well inside
  the free tier, no BI Engine needed.
- New dashboard needs = a new `rpt_` model with tests, reviewed in a PR like any code.
- Row-level security is not needed on reporting tables: they are national aggregates readable by
  `sa-reporting` only; the regional analyst keeps using the RLS-protected Gold tables.
- The trade-off: one more layer to maintain, and ad-hoc slicing beyond the reporting grain needs
  a new model (or analyst access to Gold).
