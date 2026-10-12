-- One row per alarm. Re-exported alarms keep the most recent export.
{{
    config(
        unique_key='alarm_id',
        partition_by={'field': 'raised_date', 'data_type': 'date', 'granularity': 'day'},
        cluster_by=['device_id', 'severity']
    )
}}

with batch as (
    select * from {{ ref('stg_files__alarms') }}
    {{- since_last_load() }}
)

select
    *,
    current_timestamp() as _silver_loaded_at
from batch
{{ latest_version('alarm_id', 'exported_at desc, _ingested_at desc') }}
