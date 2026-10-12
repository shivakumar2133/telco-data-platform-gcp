-- Current state of every billing account.
{{
    config(
        unique_key='account_id',
        cluster_by=['customer_id']
    )
}}

with batch as (
    select * from {{ ref('stg_oracle__billing_accounts') }}
    {{- since_last_load() }}
)

select
    *,
    current_timestamp() as _silver_loaded_at
from batch
{{ latest_version('account_id', 'updated_at desc, _ingested_at desc') }}
