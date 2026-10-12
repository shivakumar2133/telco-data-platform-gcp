{#
  Latest DQ run, one row per rule: the data quality page of the dashboards.
  A view (always current, no storage); history stays in dq_scorecard for trends.
#}
{{ config(materialized='view') }}

select
    dq_run_at,
    rule_id,
    defect_type,
    dimension,
    severity,
    checked_object,
    population,
    failed_records,
    failed_pct,
    max_failure_pct,
    status
from {{ ref('dq_scorecard') }}
where dq_run_id = (select dq_run_id from {{ ref('dq_scorecard') }} order by dq_run_at desc limit 1)
