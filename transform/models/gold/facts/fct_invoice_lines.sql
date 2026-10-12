-- Grain: one row per invoice line (recurring, usage or one-off charge).
-- The main revenue fact. Customer/product versions are those valid on the invoice date.
{{
    config(
        partition_by={'field': 'period_month', 'data_type': 'date', 'granularity': 'month'},
        cluster_by=['customer_sk', 'charge_type']
    )
}}

with lines as (
    select * from {{ ref('billing_invoice_lines') }}
),

invoices as (
    select * from {{ ref('billing_invoices') }}
),

accounts as (
    select account_id, customer_id from {{ ref('billing_accounts') }}
)

select
    l.line_id,
    l.invoice_id,
    i.account_id,
    i.period_start as period_month,
    {{ date_key('i.invoice_date') }} as invoice_date_key,
    coalesce(cu.customer_sk, -1) as customer_sk,
    coalesce(s.subscription_sk, -1) as subscription_sk,
    coalesce(p.product_sk, -1) as product_sk,
    l.charge_type,
    l.description,
    l.quantity,
    l.amount,
    i.status as invoice_status
from lines as l
left join invoices as i on i.invoice_id = l.invoice_id
left join accounts as a on a.account_id = i.account_id
left join {{ ref('dim_subscription') }} as s on s.subscription_id = l.subscription_id
left join {{ ref('dim_customer') }} as cu
    on cu.customer_id = a.customer_id and {{ as_of('cu', 'timestamp(i.invoice_date)') }}
left join {{ ref('dim_product') }} as p
    on p.product_id = s.product_id and {{ as_of('p', 'timestamp(i.period_start)') }}
