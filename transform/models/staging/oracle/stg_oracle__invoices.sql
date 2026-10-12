-- Oracle DATE carries a time part, so Bronze holds these as TIMESTAMP. Business-wise
-- they are calendar dates, so cast them to DATE here.
select
    invoice_id,
    account_id,
    date(invoice_date) as invoice_date,
    date(period_start) as period_start,
    date(period_end) as period_end,
    date(due_date) as due_date,
    total_amount,
    currency,
    status,
    created_at,
    updated_at,
    _run_id,
    _ingested_at
from {{ source('bronze', 'oracle__invoices') }}
