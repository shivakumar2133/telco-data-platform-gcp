-- 0.999 (a fraction) must have been normalised to 99.9 (a percentage).
select *
from {{ ref('service_sla_targets') }}
where availability_target_pct < 90 or availability_target_pct > 100
