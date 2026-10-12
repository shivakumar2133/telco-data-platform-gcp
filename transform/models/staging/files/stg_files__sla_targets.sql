-- SLA targets from a hand-maintained workbook. Fixes the four known defects:
--   "Enhanced " (trailing space) -> trim
--   "24 hrs"   (text in a number) -> take the number
--   0.999      (fraction, not %)  -> x100
--   a duplicated row               -> removed in the Silver model
-- The newest delivered workbook replaces earlier ones entirely.
with source as (
    select * from {{ source('bronze', 'files__sla_targets') }}
),

latest_file as (
    select * from source
    where _ingested_at = (select max(_ingested_at) from source)
),

typed as (
    select
        initcap(trim(sla_tier)) as sla_tier,
        upper(trim(priority)) as priority,
        safe_cast(regexp_extract(response_hrs, r'[0-9]+(?:\.[0-9]+)?') as numeric) as response_hours,
        safe_cast(regexp_extract(resolution_hrs, r'[0-9]+(?:\.[0-9]+)?') as numeric) as resolution_hours,
        safe_cast(availability_target as numeric) as availability_raw,
        safe_cast(substr(effective_from, 1, 10) as date) as effective_from,
        _source_file,
        _run_id,
        _ingested_at
    from latest_file
    where sla_tier is not null
)

select
    * except (availability_raw),
    case
        when availability_raw <= 1 then availability_raw * 100
        else availability_raw
    end as availability_target_pct
from typed
