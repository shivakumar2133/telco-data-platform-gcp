-- Current state of every network site.
{{
    config(
        unique_key='site_id'
    )
}}

with batch as (
    select * from {{ ref('stg_postgres__sites') }}
    {{- since_last_load() }}
)

select
    *,
    current_timestamp() as _silver_loaded_at
from batch
{{ latest_version('site_id', 'updated_at desc, _ingested_at desc') }}
