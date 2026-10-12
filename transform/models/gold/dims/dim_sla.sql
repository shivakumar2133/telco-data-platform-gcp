-- SLA targets per service tier and priority.
select
    {{ surrogate_key(['sla_tier', 'priority']) }} as sla_sk,
    sla_tier,
    priority,
    response_hours,
    resolution_hours,
    availability_target_pct,
    effective_from
from {{ ref('service_sla_targets') }}

union all

select
    -1, 'Unknown', 'UNKNOWN', cast(null as numeric), cast(null as numeric),
    cast(null as numeric), cast(null as date)
