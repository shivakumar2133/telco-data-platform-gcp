-- Network device dimension, denormalised with its site.
select
    {{ surrogate_key(['d.device_id']) }} as device_sk,
    d.device_id,
    d.device_type,
    d.vendor,
    d.model,
    d.status as device_status,
    d.install_date,
    s.site_id,
    s.site_name,
    s.site_type,
    s.region,
    s.latitude,
    s.longitude
from {{ ref('network_devices') }} as d
left join {{ ref('network_sites') }} as s on s.site_id = d.site_id

union all

select
    -1, 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', cast(null as date),
    'UNKNOWN', 'Unknown site', 'UNKNOWN', 'Unknown', cast(null as float64), cast(null as float64)
