-- Calendar dimension, one row per day 2018-2027. Lets BI tools group by month,
-- quarter, weekday etc. without date maths in every query.
with days as (
    select day from unnest(generate_date_array('2018-01-01', '2027-12-31')) as day
)

select
    {{ date_key('day') }} as date_key,
    day as date_day,
    extract(year from day) as year,
    extract(quarter from day) as quarter,
    extract(month from day) as month,
    format_date('%B', day) as month_name,
    format_date('%Y-%m', day) as year_month,
    date_trunc(day, month) as month_start,
    extract(isoweek from day) as iso_week,
    format_date('%A', day) as day_name,
    extract(dayofweek from day) in (1, 7) as is_weekend  -- BigQuery: 1 = Sunday, 7 = Saturday
from days
