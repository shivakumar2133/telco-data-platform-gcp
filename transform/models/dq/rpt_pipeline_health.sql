{#
  Pipeline health per source object, from the load audit trail: when did it last load
  successfully, how late is it, how many problems this week. The "is the data fresh?"
  page of the dashboards and the first thing to open when an alert fires.
  Thresholds match `dbt source freshness` (warn 26h, error 72h).
#}
{{ config(materialized='view') }}

with loads as (
    select
        source_system,
        -- files are logged as '<feed>/<file name>': report per feed
        if(source_system = 'files', split(object_name, '/')[offset(0)], object_name) as object_name,
        status,
        started_at,
        finished_at,
        loaded_row_count
    from {{ source('ops', 'load_audit') }}
    where started_at >= timestamp_sub(current_timestamp(), interval 30 day)  -- partition pruning
),

summary as (
    select
        source_system,
        object_name,
        max(if(status = 'SUCCESS', coalesce(finished_at, started_at), null)) as last_success_at,
        max(started_at) as last_attempt_at,
        any_value(status having max started_at) as last_status,  -- status of the latest attempt
        countif(
            status in ('FAILED', 'REJECTED')
            and started_at >= timestamp_sub(current_timestamp(), interval 7 day)
        ) as problems_last_7d,
        sum(
            if(
                status = 'SUCCESS' and started_at >= timestamp_sub(current_timestamp(), interval 7 day),
                loaded_row_count,
                0
            )
        ) as rows_loaded_last_7d
    from loads
    group by 1, 2
)

select
    source_system,
    object_name,
    last_success_at,
    last_attempt_at,
    last_status,
    problems_last_7d,
    rows_loaded_last_7d,
    timestamp_diff(current_timestamp(), last_success_at, hour) as hours_since_success,
    case
        when last_success_at is null then 'NO_SUCCESS_30D'
        when timestamp_diff(current_timestamp(), last_success_at, hour) <= 26 then 'FRESH'
        when timestamp_diff(current_timestamp(), last_success_at, hour) <= 72 then 'LATE'
        else 'STALE'
    end as freshness_status
from summary
