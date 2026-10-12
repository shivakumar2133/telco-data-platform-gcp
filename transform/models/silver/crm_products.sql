-- Current product catalogue.
{{
    config(
        unique_key='product_id'
    )
}}

with batch as (
    select * from {{ ref('stg_mssql__products') }}
    {{- since_last_load() }}
)

select
    *,
    current_timestamp() as _silver_loaded_at
from batch
{{ latest_version('product_id', 'updated_at desc, _ingested_at desc') }}
