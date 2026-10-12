-- CRM subscriptions (a customer's products). msisdn is only set for MOBILE products.
select
    subscription_id,
    customer_id,
    product_id,
    msisdn,
    start_date,
    end_date,
    status,
    created_at,
    updated_at,
    _run_id,
    _ingested_at
from {{ source('bronze', 'mssql__subscriptions') }}
