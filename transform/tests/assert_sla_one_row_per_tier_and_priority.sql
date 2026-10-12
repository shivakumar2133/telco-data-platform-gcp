-- The workbook had Premium/P1 twice. Silver must hold exactly 3 tiers x 4 priorities.
with counts as (
    select sla_tier, priority, count(*) as n
    from {{ ref('service_sla_targets') }}
    group by sla_tier, priority
)

select * from counts where n > 1
union all
select 'TOTAL' as sla_tier, cast(count(*) as string) as priority, count(*) as n
from {{ ref('service_sla_targets') }}
having count(*) != 12
