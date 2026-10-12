-- Invoice lines. No source timestamp, so the newest extraction wins.
{{
    config(
        unique_key='line_id',
        cluster_by=['invoice_id', 'subscription_id']
    )
}}

with batch as (
    select * from {{ ref('stg_oracle__invoice_lines') }}
    {{- since_last_load() }}
)

select
    *,
    current_timestamp() as _silver_loaded_at
from batch
{{ latest_version('line_id', '_ingested_at desc') }}
