select
    account_id,
    customer_id,
    billing_cycle_day,
    payment_method,
    credit_class,
    created_at,
    updated_at,
    _run_id,
    _ingested_at
from {{ source('bronze', 'oracle__billing_accounts') }}
