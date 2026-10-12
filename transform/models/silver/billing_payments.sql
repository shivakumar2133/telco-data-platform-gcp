-- Payments (append-only at source).
{{
    config(
        unique_key='payment_id',
        partition_by={'field': 'payment_date', 'data_type': 'date', 'granularity': 'month'},
        cluster_by=['invoice_id']
    )
}}

with batch as (
    select * from {{ ref('stg_oracle__payments') }}
    {{- since_last_load() }}
)

select
    *,
    current_timestamp() as _silver_loaded_at
from batch
{{ latest_version('payment_id', 'created_at desc, _ingested_at desc') }}
