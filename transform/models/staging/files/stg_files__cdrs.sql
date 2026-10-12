-- Call detail records arrive as text. SAFE_CAST returns NULL instead of failing,
-- so one bad value can't stop the load; the dq_ flags record what went wrong.
with source as (
    select * from {{ source('bronze', 'files__cdr') }}
),

typed as (
    select
        cdr_id,
        msisdn_a,
        nullif(msisdn_b, '') as msisdn_b,
        upper(call_type) as call_type,
        safe_cast(start_time as timestamp) as start_time,
        safe_cast(duration_sec as int64) as duration_sec,
        safe_cast(data_volume_mb as numeric) as data_volume_mb,
        cell_id,
        upper(call_result) as call_result,
        safe_cast(charge_amount as numeric) as charge_amount,
        -- the business day the FILE was for (cdr_YYYYMMDD.csv)
        safe.parse_date('%Y%m%d', regexp_extract(_source_file, r'(\d{8})')) as file_date,
        start_time as start_time_raw,
        _source_file,
        _run_id,
        _ingested_at
    from source
)

select
    * except (start_time_raw),
    date(start_time) as call_date,
    -- a record whose call happened before its file's day arrived late
    date(start_time) < file_date as is_late_arrival,
    start_time is null and start_time_raw is not null as dq_bad_timestamp,
    coalesce(duration_sec < 0, false) as dq_negative_duration
from typed
