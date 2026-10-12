-- Current state of every trouble ticket.
{{
    config(
        unique_key='ticket_id',
        partition_by={'field': 'opened_date', 'data_type': 'date', 'granularity': 'month'},
        cluster_by=['customer_id', 'status']
    )
}}

with batch as (
    select * from {{ ref('stg_api__tickets') }}
    {{- since_last_load() }}
)

select
    *,
    current_timestamp() as _silver_loaded_at
from batch
{{ latest_version('ticket_id', 'updated_at desc, _ingested_at desc') }}
