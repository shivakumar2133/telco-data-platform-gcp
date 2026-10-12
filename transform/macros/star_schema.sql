{#
  surrogate_key(['customer_id', 'dbt_valid_from']) -> INT64

  A deterministic integer key from business columns. FARM_FINGERPRINT is
  BigQuery's fast 64-bit hash; integer keys make fact-to-dimension joins cheaper
  than string keys. Oracle analogy: a sequence-generated key, but reproducible,
  so a full rebuild produces the same keys and facts never need re-keying.
#}
{% macro surrogate_key(columns) -%}
    farm_fingerprint(concat(
    {%- for col in columns %}
        coalesce(cast({{ col }} as string), '~null~'){% if not loop.last %}, '|',{% endif %}
    {%- endfor %}
    ))
{%- endmacro %}

{# date_key(col) -> INT64 like 20260915, the conventional date dimension key #}
{% macro date_key(column) -%}
    cast(format_date('%Y%m%d', {{ column }}) as int64)
{%- endmacro %}

{#
  as_of(alias, event_ts): join condition picking the SCD2 version that was valid
  when the event happened. valid_to is exclusive, so exactly one version matches.
#}
{% macro as_of(alias, event_ts) -%}
    {{ event_ts }} >= {{ alias }}.valid_from and {{ event_ts }} < {{ alias }}.valid_to
{%- endmacro %}
