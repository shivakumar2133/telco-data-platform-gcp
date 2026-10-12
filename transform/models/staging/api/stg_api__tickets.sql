with source as (
    select * from {{ source('bronze', 'api__tickets') }}
),

typed as (
    select
        ticket_id,
        customer_id,
        nullif(alarm_id, '') as alarm_id,
        category,
        upper(priority) as priority,
        initcap(service_level) as service_level,
        upper(status) as status,
        assignment_group,
        safe_cast(opened_at as timestamp) as opened_at,
        safe_cast(resolved_at as timestamp) as resolved_at,
        safe_cast(updated_at as timestamp) as updated_at,
        _run_id,
        _ingested_at
    from source
)

select
    *,
    date(opened_at) as opened_date,
    round(timestamp_diff(resolved_at, opened_at, minute) / 60, 2) as resolution_hours,
    status in ('RESOLVED', 'CLOSED') and resolved_at is null as dq_resolved_without_date
from typed
