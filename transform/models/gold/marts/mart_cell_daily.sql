-- Network quality per cell per day: the dropped-call rate is the headline KPI.
-- Pre-aggregated so dashboards read thousands of rows, not 1.1 million.
-- Row-level security by region + table grant for regional analysts (macros/governance.sql)
{{
    config(
        partition_by={'field': 'call_date', 'data_type': 'date', 'granularity': 'day'},
        cluster_by=['region', 'cell_id'],
        post_hook="{{ row_access_policies('region') }}",
        grants={'roles/bigquery.dataViewer': regional_principals()},
    )
}}

select
    f.call_date,
    f.date_key,
    f.cell_sk,
    c.cell_id,
    c.site_id,
    c.site_name,
    c.region,
    c.technology,
    count(*) as call_attempts,
    countif(f.call_type = 'VOICE') as voice_calls,
    countif(f.is_dropped) as dropped_calls,
    countif(f.call_result = 'FAILED') as failed_calls,
    safe_divide(countif(f.is_dropped), count(*)) as drop_rate,
    round(sum(case when f.call_type = 'VOICE' and f.duration_sec > 0 then f.duration_sec end) / 60, 1)
        as voice_minutes,
    round(sum(f.data_volume_mb) / 1024, 3) as data_gb
from {{ ref('fct_calls') }} as f
left join {{ ref('dim_cell') }} as c on c.cell_sk = f.cell_sk
group by 1, 2, 3, 4, 5, 6, 7, 8
