-- Current state of every invoice. Monthly partitions on the billing period.
{{
    config(
        unique_key='invoice_id',
        partition_by={'field': 'period_start', 'data_type': 'date', 'granularity': 'month'},
        cluster_by=['account_id', 'status']
    )
}}

with batch as (
    select * from {{ ref('stg_oracle__invoices') }}
    {{- since_last_load() }}
)

select
    *,
    current_timestamp() as _silver_loaded_at
from batch
{{ latest_version('invoice_id', 'updated_at desc, _ingested_at desc') }}
