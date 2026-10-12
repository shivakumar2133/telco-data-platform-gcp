{#
  Record-level DQ failures: one row per failing record per run, with the whole
  record as JSON. This is the quarantine/exception table: you can see exactly
  WHICH customers, calls or invoices failed, not just how many.

  Append-only (no unique_key): every run adds its findings, history is kept.
  full_refresh=false protects that history from `dbt build --full-refresh`.
  Oracle analogy: DBMS_ERRLOG's ERR$_ table, but for business rules.
#}
{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    full_refresh=false,
    partition_by={'field': 'detected_date', 'data_type': 'date'},
    partition_expiration_days=90,
    cluster_by=['rule_id'],
) }}

with failures as (
  {% for r in dq_rules() %}
    select
        {{ sql_string(r.id) }} as rule_id,
        cast({{ r.key }} as string) as record_key,
        to_json_string(t) as record_json
    from {{ r.relation }} as t
    where ({{ r.fail_if }})
      {%- if r.get('scope') %} and ({{ r.scope }}){% endif %}
  {% if not loop.last %}union all{% endif %}
  {% endfor %}
),

catalog as (
  {% for r in dq_rules() %}
    select {{ sql_string(r.id) }} as rule_id, {{ sql_string(r.defect_type) }} as defect_type,
           {{ sql_string(r.dimension) }} as dimension, {{ sql_string(r.severity) }} as severity
  {% if not loop.last %}union all{% endif %}
  {% endfor %}
)

select
    '{{ invocation_id }}' as dq_run_id,
    {{ dq_run_at() }} as detected_at,
    date({{ dq_run_at() }}) as detected_date,
    f.rule_id,
    c.defect_type,
    c.dimension,
    c.severity,
    f.record_key,
    f.record_json
from failures as f
join catalog as c using (rule_id)
