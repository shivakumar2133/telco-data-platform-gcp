-- REVENUE ASSURANCE: for every subscription and month that has call records, compare
-- what the network RATED (sum of CDR charges) with what billing INVOICED (USAGE lines).
--
--   MATCHED              billed = rated (to the penny)
--   LEAKAGE              usage rated but nothing billed       -> money lost
--   UNBILLED_NO_ACCOUNT  usage rated, but the subscription's customer has no billing
--                        account (orphan in CRM) - can never be billed until fixed
--   UNDER_BILLED / OVER_BILLED  both present but different
--
-- Grain: one row per subscription per month.
with rated as (
    select
        f.subscription_sk,
        date_trunc(f.call_date, month) as usage_month,
        sum(f.charge_amount) as rated_amount,
        count(*) as cdr_count
    from {{ ref('fct_calls') }} as f
    group by 1, 2
),

months as (
    select distinct usage_month from rated
),

billed as (
    select
        l.subscription_sk,
        l.period_month as usage_month,
        sum(l.amount) as billed_amount
    from {{ ref('fct_invoice_lines') }} as l
    where l.charge_type = 'USAGE'
      and l.period_month in (select usage_month from months)
    group by 1, 2
),

compared as (
    select
        coalesce(r.subscription_sk, b.subscription_sk) as subscription_sk,
        coalesce(r.usage_month, b.usage_month) as usage_month,
        coalesce(r.rated_amount, 0) as rated_amount,
        coalesce(b.billed_amount, 0) as billed_amount,
        coalesce(r.cdr_count, 0) as cdr_count
    from rated as r
    full outer join billed as b
        on b.subscription_sk = r.subscription_sk and b.usage_month = r.usage_month
)

select
    c.usage_month,
    c.subscription_sk,
    s.subscription_id,
    s.customer_id,
    c.cdr_count,
    c.rated_amount,
    c.billed_amount,
    c.rated_amount - c.billed_amount as variance_amount,
    case
        when abs(c.rated_amount - c.billed_amount) <= 0.005 then 'MATCHED'
        when c.billed_amount = 0 and s.has_no_billing_account then 'UNBILLED_NO_ACCOUNT'
        when c.billed_amount = 0 then 'LEAKAGE'
        when c.billed_amount < c.rated_amount then 'UNDER_BILLED'
        else 'OVER_BILLED'
    end as assurance_status
from compared as c
left join {{ ref('dim_subscription') }} as s on s.subscription_sk = c.subscription_sk
