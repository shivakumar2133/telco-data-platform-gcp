-- The DQ framework checks itself: for the latest run, the failure count on the
-- scorecard must equal the distinct failing keys written to the quarantine table.
with latest as (
    select dq_run_id from {{ ref('dq_scorecard') }} order by dq_run_at desc limit 1
),
quarantined as (
    select rule_id, count(distinct record_key) as n
    from {{ ref('dq_failures') }}
    where dq_run_id = (select dq_run_id from latest)
    group by rule_id
)
select s.rule_id, s.failed_records, coalesce(q.n, 0) as quarantined_records
from {{ ref('dq_scorecard') }} as s
left join quarantined as q using (rule_id)
where s.dq_run_id = (select dq_run_id from latest)
  and s.failed_records != coalesce(q.n, 0)
