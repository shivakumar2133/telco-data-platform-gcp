{#
  Financial reconciliation as a test: SUM(column) in the model must equal the SUM
  in the relation it was built from (to the penny). Catches rows lost or duplicated
  by joins (fan-out), which a row count alone can miss.

    - column_sum_matches:
        arguments:
          compare_relation: ref('billing_invoice_lines')
          compare_column: amount
#}
{% test column_sum_matches(model, column_name, compare_relation, compare_column=none, tolerance=0.005) %}
with a as (select coalesce(sum({{ column_name }}), 0) as total from {{ model }}),
     b as (select coalesce(sum({{ compare_column or column_name }}), 0) as total from {{ compare_relation }})
select a.total as model_total, b.total as source_total
from a cross join b
where abs(a.total - b.total) > {{ tolerance }}
{% endtest %}
