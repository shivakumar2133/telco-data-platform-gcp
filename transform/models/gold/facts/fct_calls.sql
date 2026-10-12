-- Grain: one row per call detail record.
-- The customer and product are the VERSIONS valid at the moment of the call (SCD2 as-of
-- join), so a customer who moved region in October still shows September calls under
-- their September region. Unresolvable references point to the Unknown member (-1).
{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='cdr_id',
        partition_by={'field': 'call_date', 'data_type': 'date', 'granularity': 'day'},
        cluster_by=['cell_sk', 'customer_sk']
    )
}}

with calls as (
    select * from {{ ref('usage_cdrs') }}
    {{- since_last_load('_silver_loaded_at') }}
)

select
    c.cdr_id,
    c.call_date,
    {{ date_key('c.call_date') }} as date_key,
    c.start_time,
    coalesce(cu.customer_sk, -1) as customer_sk,
    coalesce(s.subscription_sk, -1) as subscription_sk,
    coalesce(p.product_sk, -1) as product_sk,
    coalesce(ce.cell_sk, -1) as cell_sk,
    c.call_type,
    c.call_result,
    c.duration_sec,
    c.data_volume_mb,
    c.charge_amount,
    c.call_result = 'DROPPED' as is_dropped,
    c.is_late_arrival,
    c.dq_negative_duration,
    ce.cell_sk is null as dq_unknown_cell,
    s.subscription_sk is null as dq_unknown_msisdn,
    c._silver_loaded_at
from calls as c
left join {{ ref('dim_subscription') }} as s
    on s.msisdn = c.msisdn_a
left join {{ ref('dim_customer') }} as cu
    on cu.customer_id = s.customer_id and {{ as_of('cu', 'c.start_time') }}
left join {{ ref('dim_product') }} as p
    on p.product_id = s.product_id and {{ as_of('p', 'c.start_time') }}
left join {{ ref('dim_cell') }} as ce
    on ce.cell_id = c.cell_id
