-- Current state of every subscription.
{{
    config(
        unique_key='subscription_id',
        cluster_by=['customer_id', 'subscription_id']
    )
}}

with batch as (
    select * from {{ ref('stg_mssql__subscriptions') }}
    {{- since_last_load() }}
)

select
    *,
    current_timestamp() as _silver_loaded_at
from batch
{{ latest_version('subscription_id', 'updated_at desc, _ingested_at desc') }}
