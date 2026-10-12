-- Current state of every CRM customer (latest version per customer_id).
{{
    config(
        unique_key='customer_id',
        cluster_by=['customer_id']
    )
}}

with batch as (
    select * from {{ ref('stg_mssql__customers') }}
    {{- since_last_load() }}
)

select
    *,
    current_timestamp() as _silver_loaded_at
from batch
{{ latest_version('customer_id', 'updated_at desc, _ingested_at desc') }}
