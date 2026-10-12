-- Radio cell dimension, denormalised with its site (a star, not a snowflake:
-- BI tools get region/site in one join).
select
    {{ surrogate_key(['c.cell_id']) }} as cell_sk,
    c.cell_id,
    c.technology,
    c.band,
    c.sector,
    c.status as cell_status,
    c.commissioned_date,
    s.site_id,
    s.site_name,
    s.site_type,
    s.region,
    s.postcode,
    s.latitude,
    s.longitude
from {{ ref('network_cells') }} as c
left join {{ ref('network_sites') }} as s on s.site_id = c.site_id

union all

select
    -1, 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', cast(null as int64), 'UNKNOWN', cast(null as date),
    'UNKNOWN', 'Unknown site', 'UNKNOWN', 'Unknown', cast(null as string),
    cast(null as float64), cast(null as float64)
