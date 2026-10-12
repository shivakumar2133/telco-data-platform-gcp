-- Network alarms: the nested JSON was flattened in Bronze (device__device_id ...).
with source as (
    select * from {{ source('bronze', 'files__alarms') }}
),

typed as (
    select
        alarm_id,
        device__device_id as device_id,
        device__site_id as site_id,
        device__device_type as device_type,
        device__vendor as vendor,
        upper(severity) as severity,
        alarm_type,
        safe_cast(raised_at as timestamp) as raised_at,
        safe_cast(cleared_at as timestamp) as cleared_at,
        attributes__probable_cause as probable_cause,
        attributes__interface as interface_name,
        attributes__vendor_code as vendor_code,
        export_id,
        safe_cast(exported_at as timestamp) as exported_at,
        _source_file,
        _run_id,
        _ingested_at
    from source
)

select
    *,
    date(raised_at) as raised_date,
    cleared_at is null as is_open,
    coalesce(cleared_at < raised_at, false) as dq_cleared_before_raised,
    case
        when cleared_at >= raised_at then timestamp_diff(cleared_at, raised_at, minute)
    end as duration_minutes
from typed
