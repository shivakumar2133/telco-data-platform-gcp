-- CRM product catalogue.
select
    product_id,
    product_name,
    product_type,
    segment as target_segment,
    monthly_fee,
    data_allowance_gb,
    minutes_allowance,
    data_allowance_gb is null as is_unlimited_data,
    minutes_allowance is null as is_unlimited_minutes,
    sla_tier,
    created_at,
    updated_at,
    _run_id,
    _ingested_at
from {{ source('bronze', 'mssql__products') }}
