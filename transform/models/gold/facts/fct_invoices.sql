-- Grain: one row per invoice. Header amount alongside the sum of its lines and its
-- payments, so billing integrity and collections can be reported directly.
{{
    config(
        partition_by={'field': 'period_month', 'data_type': 'date', 'granularity': 'month'},
        cluster_by=['customer_sk', 'invoice_status']
    )
}}

with lines as (
    select invoice_id, sum(amount) as lines_total, count(*) as line_count
    from {{ ref('billing_invoice_lines') }}
    group by invoice_id
),

payments as (
    select invoice_id, sum(amount) as paid_amount, max(payment_date) as last_payment_date
    from {{ ref('billing_payments') }}
    group by invoice_id
)

select
    i.invoice_id,
    i.account_id,
    i.period_start as period_month,
    {{ date_key('i.invoice_date') }} as invoice_date_key,
    {{ date_key('i.due_date') }} as due_date_key,
    coalesce(cu.customer_sk, -1) as customer_sk,
    i.status as invoice_status,
    i.total_amount,
    coalesce(l.lines_total, 0) as lines_total,
    coalesce(l.line_count, 0) as line_count,
    coalesce(p.paid_amount, 0) as paid_amount,
    i.total_amount - coalesce(p.paid_amount, 0) as outstanding_amount,
    p.last_payment_date,
    abs(i.total_amount - coalesce(l.lines_total, 0)) > 0.005 as dq_header_line_mismatch
from {{ ref('billing_invoices') }} as i
left join lines as l on l.invoice_id = i.invoice_id
left join payments as p on p.invoice_id = i.invoice_id
left join {{ ref('billing_accounts') }} as a on a.account_id = i.account_id
left join {{ ref('dim_customer') }} as cu
    on cu.customer_id = a.customer_id and {{ as_of('cu', 'timestamp(i.invoice_date)') }}
