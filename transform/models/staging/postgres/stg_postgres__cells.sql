select
    cell_id,
    site_id,
    technology,
    band,
    sector,
    commissioned_date,
    status,
    updated_at,
    _run_id,
    _ingested_at
from {{ source('bronze', 'postgres__cells') }}
