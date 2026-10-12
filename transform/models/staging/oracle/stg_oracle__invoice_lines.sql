select
    line_id,
    invoice_id,
    subscription_id,
    charge_type,
    description,
    quantity,
    amount,
    _run_id,
    _ingested_at
from {{ source('bronze', 'oracle__invoice_lines') }}
