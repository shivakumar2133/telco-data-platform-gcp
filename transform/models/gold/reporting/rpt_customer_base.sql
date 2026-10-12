-- Current customer base per region x segment x status, with active subscriptions.
-- Counts only - no names, emails or postcodes (those stay behind column-level security).
with subs as (
    select
        customer_id,
        countif(status = 'ACTIVE') as active_subscriptions
    from {{ ref('dim_subscription') }}
    where subscription_sk != -1
    group by 1
)

select
    c.region,
    c.segment as customer_segment,
    c.status as customer_status,
    count(*) as customers,
    countif(c.is_valid_email) as customers_with_valid_email,
    sum(coalesce(s.active_subscriptions, 0)) as active_subscriptions
from {{ ref('dim_customer') }} as c
left join subs as s on c.customer_id = s.customer_id
where c.is_current and c.customer_sk != -1
group by 1, 2, 3
