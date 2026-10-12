-- Product dimension, SCD Type 2: a price change creates a new version, so revenue is
-- always reported against the price that applied at the time.
with versions as (
    select
        *,
        row_number() over (partition by product_id order by dbt_valid_from) as version_number
    from {{ ref('crm_products_snapshot') }}
)

select
    {{ surrogate_key(['product_id', 'dbt_valid_from']) }} as product_sk,
    product_id,
    version_number,
    product_name,
    product_type,
    target_segment,
    monthly_fee,
    data_allowance_gb,
    minutes_allowance,
    is_unlimited_data,
    is_unlimited_minutes,
    sla_tier,
    case when version_number = 1 then timestamp('1900-01-01') else dbt_valid_from end as valid_from,
    dbt_valid_to as valid_to,
    dbt_valid_to = timestamp('9999-12-31') as is_current
from versions

union all

select
    -1, 'UNKNOWN', 0, 'Unknown product', 'UNKNOWN', 'Unknown', cast(null as numeric),
    cast(null as int64), cast(null as int64), false, false, 'Standard',
    timestamp('1900-01-01'), timestamp('9999-12-31'), true
