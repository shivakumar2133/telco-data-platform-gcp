-- One row per call detail record. Duplicate deliveries of the same cdr_id collapse to one row;
-- late arrivals land in the partition of the day the call happened, not the file's day.
{{
    config(
        unique_key='cdr_id',
        partition_by={'field': 'call_date', 'data_type': 'date', 'granularity': 'day'},
        cluster_by=['msisdn_a', 'cell_id']
    )
}}

with batch as (
    select * from {{ ref('stg_files__cdrs') }}
    {{- since_last_load() }}
)

select
    *,
    current_timestamp() as _silver_loaded_at
from batch
{{ latest_version('cdr_id', '_ingested_at') }}
