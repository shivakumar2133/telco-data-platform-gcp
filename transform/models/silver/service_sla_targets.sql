-- SLA targets: a small reference table, rebuilt in full from the newest workbook.
-- (Incremental makes no sense for 12 rows that are replaced as a whole.)
{{ config(materialized='table') }}

select
    sla_tier,
    priority,
    response_hours,
    resolution_hours,
    availability_target_pct,
    effective_from,
    _source_file,
    _ingested_at,
    current_timestamp() as _silver_loaded_at
from {{ ref('stg_files__sla_targets') }}
qualify row_number() over (partition by sla_tier, priority order by _source_file) = 1
