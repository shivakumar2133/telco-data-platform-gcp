-- Grain: one row per network alarm, with whether it produced a customer ticket.
{{
    config(
        partition_by={'field': 'raised_date', 'data_type': 'date', 'granularity': 'day'},
        cluster_by=['device_sk', 'severity']
    )
}}

with ticketed as (
    select alarm_id, min(ticket_id) as first_ticket_id, count(*) as ticket_count
    from {{ ref('service_tickets') }}
    where alarm_id is not null
    group by alarm_id
)

select
    a.alarm_id,
    a.raised_date,
    {{ date_key('a.raised_date') }} as raised_date_key,
    coalesce(d.device_sk, -1) as device_sk,
    a.severity,
    a.alarm_type,
    a.probable_cause,
    a.raised_at,
    a.cleared_at,
    a.duration_minutes,
    a.is_open,
    t.alarm_id is not null as has_ticket,
    t.first_ticket_id,
    coalesce(t.ticket_count, 0) as ticket_count,
    a.dq_cleared_before_raised,
    d.device_sk is null as dq_unknown_device
from {{ ref('network_alarms') }} as a
left join {{ ref('dim_device') }} as d on d.device_id = a.device_id
left join ticketed as t on t.alarm_id = a.alarm_id
