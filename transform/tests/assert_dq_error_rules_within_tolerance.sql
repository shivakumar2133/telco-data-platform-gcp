-- Quality gate: an ERROR-severity rule above its tolerance stops the pipeline,
-- so Gold is never published (gold_ready) on top of broken data.
select rule_id, failed_records, population, failed_pct, max_failure_pct
from {{ ref('dq_scorecard') }}
where
    dq_run_id = (select dq_run_id from {{ ref('dq_scorecard') }} order by dq_run_at desc limit 1)
    and severity = 'error'
    and status = 'BREACHED'
