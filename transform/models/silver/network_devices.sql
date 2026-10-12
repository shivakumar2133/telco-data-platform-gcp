-- Current state of every network device.
{{
    config(
        unique_key='device_id',
        cluster_by=['site_id']
    )
}}

with batch as (
    select * from {{ ref('stg_postgres__devices') }}
    {{- since_last_load() }}
)

select
    *,
    current_timestamp() as _silver_loaded_at
from batch
{{ latest_version('device_id', 'updated_at desc, _ingested_at desc') }}
