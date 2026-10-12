{#
  The rule catalogue as a table, so dashboards and analysts can see WHAT is checked,
  how strictly, and why - without reading SQL. Generated from macros/dq_rules.sql.
#}
{{ config(materialized='table') }}

{% for r in dq_rules() %}
select
    {{ sql_string(r.id) }} as rule_id,
    {{ sql_string(r.defect_type) }} as defect_type,
    {{ sql_string(r.dimension) }} as dimension,
    {{ sql_string(r.severity) }} as severity,
    cast({{ r.max_failure_pct }} as float64) as max_failure_pct,
    {{ sql_string(r.object) }} as checked_object,
    {{ sql_string(r.key) }} as record_key_expression,
    {{ sql_string(r.fail_if) }} as fail_condition,
    {{ sql_string(r.get('scope')) }} as scope_condition,
    {{ sql_string(r.description) }} as description
{% if not loop.last %}union all{% endif %}
{% endfor %}
