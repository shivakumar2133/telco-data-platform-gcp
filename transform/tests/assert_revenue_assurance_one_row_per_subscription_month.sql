-- The mart's grain is subscription x month. A duplicate means a join fanned out.
select subscription_sk, usage_month, count(*) as n
from {{ ref('mart_revenue_assurance') }}
group by 1, 2
having count(*) > 1
