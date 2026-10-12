-- One row per month with the headline KPIs: the executive page of every dashboard.
-- Each block is aggregated on its own grain first, then joined on the month, so no
-- block can multiply another (the classic fan-out mistake in KPI tables).
with billing as (
    select
        period_month as month,
        sum(amount) as billed_revenue,
        sum(case when charge_type = 'USAGE' then amount else 0 end) as billed_usage
    from {{ ref('fct_invoice_lines') }}
    group by 1
),

assurance as (
    select
        usage_month as month,
        sum(rated_amount) as rated_usage,
        sum(case when assurance_status in ('LEAKAGE', 'UNBILLED_NO_ACCOUNT') then variance_amount else 0 end)
            as unbilled_usage,
        sum(case when assurance_status = 'LEAKAGE' then subscriptions else 0 end)
            as leakage_subscriptions
    from {{ ref('rpt_revenue_assurance') }}
    group by 1
),

network as (
    select
        date_trunc(call_date, month) as month,
        sum(call_attempts) as call_attempts,
        sum(dropped_calls) as dropped_calls,
        sum(voice_minutes) as voice_minutes,
        sum(data_gb) as data_gb
    from {{ ref('rpt_network_daily') }}
    group by 1
),

service as (
    select
        opened_month as month,
        sum(tickets) as tickets,
        sum(measured_tickets) as measured_tickets,
        sum(breached_tickets) as breached_tickets
    from {{ ref('rpt_sla_performance') }}
    group by 1
),

months as (
    select month from billing
    union distinct
    select month from assurance
    union distinct
    select month from network
    union distinct
    select month from service
)

select
    m.month,
    b.billed_revenue,
    b.billed_usage,
    a.rated_usage,
    a.unbilled_usage,
    a.leakage_subscriptions,
    n.call_attempts,
    n.dropped_calls,
    n.voice_minutes,
    n.data_gb,
    s.tickets,
    s.measured_tickets,
    s.breached_tickets
from months as m
left join billing as b on m.month = b.month
left join assurance as a on m.month = a.month
left join network as n on m.month = n.month
left join service as s on m.month = s.month
