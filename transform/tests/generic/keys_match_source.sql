{#
  Reconciliation as a test: every distinct key in the source must appear exactly
  once in the model. Fails (returns a row) when the counts differ.

    - keys_match_source:
        arguments:
          source_relation: source('bronze', 'mssql__customers')
#}
{% test keys_match_source(model, column_name, source_relation, source_column=none) %}
{%- set src_col = source_column or column_name -%}
with source_keys as (
    select count(distinct {{ src_col }}) as n from {{ source_relation }}
),
model_keys as (
    select count(*) as n from {{ model }}
)
select s.n as source_distinct_keys, m.n as model_rows
from source_keys as s
cross join model_keys as m
where s.n != m.n
{% endtest %}
