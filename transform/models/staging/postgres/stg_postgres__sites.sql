select
    site_id,
    site_name,
    site_type,
    region,
    upper(trim(postcode)) as postcode,
    cast(latitude as float64) as latitude,
    cast(longitude as float64) as longitude,
    created_at,
    updated_at,
    _run_id,
    _ingested_at
from {{ source('bronze', 'postgres__sites') }}
