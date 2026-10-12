-- Grain: one row per trouble ticket, measured against its SLA target.
{{
    config(
        partition_by={'field': 'opened_date', 'data_type': 'date', 'granularity': 'month'},
        cluster_by=['customer_sk', 'priority']
    )
}}

select
    t.ticket_id,
    t.opened_date,
    {{ date_key('t.opened_date') }} as opened_date_key,
    coalesce(cu.customer_sk, -1) as customer_sk,
    coalesce(sla.sla_sk, -1) as sla_sk,
    t.alarm_id,
    t.category,
    t.priority,
    t.service_level,
    t.status,
    t.assignment_group,
    t.opened_at,
    t.resolved_at,
    t.resolution_hours,
    sla.resolution_hours as sla_resolution_target_hours,
    case
        when t.resolution_hours is null then null
        else t.resolution_hours > sla.resolution_hours
    end as is_sla_breached,
    t.status in ('NEW', 'IN_PROGRESS') as is_open,
    t.dq_resolved_without_date,
    cu.customer_sk is null as dq_unknown_customer
from {{ ref('service_tickets') }} as t
left join {{ ref('dim_customer') }} as cu
    on cu.customer_id = t.customer_id and {{ as_of('cu', 't.opened_at') }}
left join {{ ref('dim_sla') }} as sla
    on sla.sla_tier = t.service_level and sla.priority = t.priority
