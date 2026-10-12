select
    payment_id,
    invoice_id,
    date(payment_date) as payment_date,
    amount,
    payment_method,
    created_at,
    _run_id,
    _ingested_at
from {{ source('bronze', 'oracle__payments') }}
