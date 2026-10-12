-- Revenue assurance for dashboards: one row per month x status x segment x region x product.
-- Reporting tables use only untagged columns, so BI tools (sa-reporting) can SELECT *
-- without hitting column-level security, and a shared dashboard can never leak PII.
with ra as (
    select * from {{ ref('mart_revenue_assurance') }}
),

subscriptions as (
    select subscription_sk, customer_id, product_id from {{ ref('dim_subscription') }}
),

customers as (
    select customer_id, segment, region from {{ ref('dim_customer') }}
    where is_current
),

products as (
    select product_id, product_name, product_type from {{ ref('dim_product') }}
    where is_current
)

select
    ra.usage_month,
    ra.assurance_status,
    coalesce(c.segment, 'Unknown') as customer_segment,
    coalesce(c.region, 'Unknown') as region,
    coalesce(p.product_name, 'Unknown') as product_name,
    coalesce(p.product_type, 'Unknown') as product_type,
    count(distinct ra.subscription_id) as subscriptions,
    sum(ra.cdr_count) as cdr_count,
    sum(ra.rated_amount) as rated_amount,
    sum(ra.billed_amount) as billed_amount,
    sum(ra.variance_amount) as variance_amount
from ra
left join subscriptions as s on ra.subscription_sk = s.subscription_sk
left join customers as c on s.customer_id = c.customer_id
left join products as p on s.product_id = p.product_id
group by 1, 2, 3, 4, 5, 6
