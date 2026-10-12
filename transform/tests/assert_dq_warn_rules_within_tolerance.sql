-- WARN-severity rules above tolerance are reported (dbt warning + alert) but don't block.
{{ config(severity='warn') }}
select rule_id, failed_records, population, failed_pct, max_failure_pct
from {{ ref('dq_scorecard') }}
where
    dq_run_id = (select dq_run_id from {{ ref('dq_scorecard') }} order by dq_run_at desc limit 1)
    and severity = 'warn'
    and status = 'BREACHED'
