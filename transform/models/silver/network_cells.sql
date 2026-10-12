-- Current state of every radio cell.
{{
    config(
        unique_key='cell_id',
        cluster_by=['site_id']
    )
}}

with batch as (
    select * from {{ ref('stg_postgres__cells') }}
    {{- since_last_load() }}
)

select
    *,
    current_timestamp() as _silver_loaded_at
from batch
{{ latest_version('cell_id', 'updated_at desc, _ingested_at desc') }}
