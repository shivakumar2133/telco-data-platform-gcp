-- SLA performance per month x priority x service level x category. Additive counts only:
-- breach % = breached_tickets / measured_tickets, average resolution =
-- total_resolution_hours / measured_tickets (computed in the BI tool).
select
    date_trunc(opened_date, month) as opened_month,
    priority,
    service_level,
    category,
    count(*) as tickets,
    countif(is_open) as open_tickets,
    countif(not is_open) as closed_tickets,
    countif(resolution_hours is not null) as measured_tickets,
    countif(is_sla_breached) as breached_tickets,
    sum(resolution_hours) as total_resolution_hours,
    countif(dq_resolved_without_date) as tickets_missing_resolution_time,
    countif(alarm_id is not null) as tickets_from_network_alarms
from {{ ref('fct_tickets') }}
group by 1, 2, 3, 4
