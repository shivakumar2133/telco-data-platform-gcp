-- Network quality per day x region x technology. Only additive counts: rates such as the
-- drop rate are computed in the BI tool as SUM(dropped) / SUM(attempts). Averaging
-- pre-computed daily rates would weight a quiet cell the same as a busy one.
select
    call_date,
    date_key,
    coalesce(region, 'Unknown') as region,
    coalesce(technology, 'Unknown') as technology,
    count(distinct cell_id) as active_cells,
    sum(call_attempts) as call_attempts,
    sum(voice_calls) as voice_calls,
    sum(dropped_calls) as dropped_calls,
    sum(failed_calls) as failed_calls,
    sum(voice_minutes) as voice_minutes,
    sum(data_gb) as data_gb
from {{ ref('mart_cell_daily') }}
group by 1, 2, 3, 4
