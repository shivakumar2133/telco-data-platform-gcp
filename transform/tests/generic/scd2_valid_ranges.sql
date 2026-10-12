{#
  SCD Type 2 integrity for one natural key (column_name):
    - consecutive versions touch exactly (next.valid_from = this.valid_to): no gaps, no overlaps
    - every range is non-empty (valid_from < valid_to)
    - exactly one current version (valid_to = 9999-12-31)
  If any of these break, an as-of join returns zero or two rows for some events.
#}
{% test scd2_valid_ranges(model, column_name) %}
with ordered as (
    select
        {{ column_name }} as natural_key,
        valid_from,
        valid_to,
        lead(valid_from) over (partition by {{ column_name }} order by valid_from) as next_valid_from
    from {{ model }}
    where {{ column_name }} != 'UNKNOWN'
),

current_counts as (
    select {{ column_name }} as natural_key, countif(valid_to = timestamp('9999-12-31')) as n_current
    from {{ model }}
    group by 1
)

select natural_key, 'gap_or_overlap' as issue from ordered
where next_valid_from is not null and next_valid_from != valid_to
union all
select natural_key, 'empty_range' as issue from ordered
where valid_from >= valid_to
union all
select natural_key, 'not_exactly_one_current' as issue from current_counts
where n_current != 1
{% endtest %}
