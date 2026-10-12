select
    device_id,
    site_id,
    device_type,
    vendor,
    model,
    serial_number,
    install_date,
    status,
    updated_at,
    _run_id,
    _ingested_at
from {{ source('bronze', 'postgres__devices') }}
