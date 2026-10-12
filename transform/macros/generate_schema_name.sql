{#
  dbt's default would build "silver_silver" (target dataset + custom schema).
  Our datasets are created by Terraform with exact names, so use the custom
  schema as-is. This also means dbt never needs permission to create datasets.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}{{ target.schema }}{%- else -%}{{ custom_schema_name | trim }}{%- endif -%}
{%- endmacro %}
