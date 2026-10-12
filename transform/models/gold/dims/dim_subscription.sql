-- Subscription dimension (Type 1: current state). It is the bridge from a phone
-- number (msisdn on a CDR) to the customer and product.
with subs as (
    select * from {{ ref('crm_subscriptions') }}
),

customers as (
    select customer_id from {{ ref('crm_customers') }}
),

accounts as (
    select distinct customer_id from {{ ref('billing_accounts') }}
)

select
    {{ surrogate_key(['s.subscription_id']) }} as subscription_sk,
    s.subscription_id,
    s.customer_id,
    s.product_id,
    s.msisdn,
    s.start_date,
    s.end_date,
    s.status,
    c.customer_id is null as is_orphan,           -- customer no longer in CRM
    a.customer_id is null as has_no_billing_account
from subs as s
left join customers as c on c.customer_id = s.customer_id
left join accounts as a on a.customer_id = s.customer_id

union all

select
    -1, 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', cast(null as string), cast(null as date),
    cast(null as date), 'UNKNOWN', true, true
