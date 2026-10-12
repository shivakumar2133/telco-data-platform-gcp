{#
  One row per rule per run: how many records were checked, how many failed,
  and whether that is within the agreed tolerance.

    status CLEAN     no failures
           TOLERATED failures, but within max_failure_pct
           BREACHED  above tolerance -> severity decides: error stops the pipeline
                     (tests/assert_dq_error_rules_within_tolerance.sql), warn alerts.

  Population and failures are counted in ONE scan per rule (COUNT DISTINCT with
  CASE), so the scorecard costs about the same as the failures query.
#}
{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    full_refresh=false,
    partition_by={'field': 'dq_run_date', 'data_type': 'date'},
    cluster_by=['rule_id'],
) }}

with measured as (
  {% for r in dq_rules() %}
    select
        {{ sql_string(r.id) }} as rule_id,
        {{ sql_string(r.defect_type) }} as defect_type,
        {{ sql_string(r.dimension) }} as dimension,
        {{ sql_string(r.severity) }} as severity,
        {{ sql_string(r.object) }} as checked_object,
        cast({{ r.max_failure_pct }} as float64) as max_failure_pct,
        count(distinct cast({{ r.key }} as string)) as population,
        count(distinct case when ({{ r.fail_if }}) then cast({{ r.key }} as string) end) as failed_records
    from {{ r.relation }} as t
    {%- if r.get('scope') %}
    where ({{ r.scope }})
    {%- endif %}
  {% if not loop.last %}union all{% endif %}
  {% endfor %}
),

scored as (
    select
        *,
        round(100 * safe_divide(failed_records, population), 4) as failed_pct
    from measured
)

select
    '{{ invocation_id }}' as dq_run_id,
    {{ dq_run_at() }} as dq_run_at,
    date({{ dq_run_at() }}) as dq_run_date,
    rule_id,
    defect_type,
    dimension,
    severity,
    checked_object,
    population,
    failed_records,
    failed_pct,
    max_failure_pct,
    case
        when failed_records = 0 then 'CLEAN'
        when coalesce(failed_pct, 100) <= max_failure_pct then 'TOLERATED'
        else 'BREACHED'
    end as status
from scored
