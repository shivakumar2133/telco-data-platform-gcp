{#
  since_last_load(): on an incremental run, read only Bronze rows ingested after
  the newest row already in this table. This is what makes the MERGE cheap:
  the window functions and the merge only see the new batch, not all of history.
#}
{% macro since_last_load(column='_ingested_at') -%}
    {%- if is_incremental() %}
    where {{ column }} > (select coalesce(max({{ column }}), timestamp('1900-01-01')) from {{ this }})
    {%- endif %}
{%- endmacro %}

{#
  latest_version(): keep one row per key - the newest version.
  Oracle analogy: ROW_NUMBER() OVER (PARTITION BY key ORDER BY updated_at DESC) = 1,
  but BigQuery's QUALIFY filters on it without a sub-query.
#}
{% macro latest_version(key, order_by) -%}
    qualify row_number() over (partition by {{ key }} order by {{ order_by }}) = 1
{%- endmacro %}
