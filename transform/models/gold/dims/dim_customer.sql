-- Customer dimension, SCD Type 2 (one row per customer VERSION) from the dbt snapshot.
--
-- Two details that matter:
--  * the FIRST version is made valid from 1900-01-01. A snapshot version only starts
--    at the row's updated_at, so without this, July calls for a customer last edited
--    in August would find no matching version.
--  * an Unknown member (customer_sk = -1) so facts whose customer can't be resolved
--    (orphan subscriptions, unknown ticket customers) are kept, not dropped.
-- Row-level security by region + table grant for regional analysts (macros/governance.sql)
{{ config(
    cluster_by=['customer_id'],
    post_hook="{{ row_access_policies('region') }}",
    grants={'roles/bigquery.dataViewer': regional_principals()},
) }}

with versions as (
    select
        *,
        row_number() over (partition by customer_id order by dbt_valid_from) as version_number
    from {{ ref('crm_customers_snapshot') }}
)

select
    {{ surrogate_key(['customer_id', 'dbt_valid_from']) }} as customer_sk,
    customer_id,
    version_number,
    segment,
    coalesce(company_name, concat(first_name, ' ', last_name)) as customer_name,
    first_name,
    last_name,
    company_name,
    email,
    is_valid_email,
    region,
    city,
    postcode,
    is_valid_postcode,
    status,
    case when version_number = 1 then timestamp('1900-01-01') else dbt_valid_from end as valid_from,
    dbt_valid_to as valid_to,
    dbt_valid_to = timestamp('9999-12-31') as is_current
from versions

union all

select
    -1 as customer_sk,
    'UNKNOWN' as customer_id,
    0 as version_number,
    'Unknown' as segment,
    'Unknown customer' as customer_name,
    cast(null as string) as first_name,
    cast(null as string) as last_name,
    cast(null as string) as company_name,
    cast(null as string) as email,
    false as is_valid_email,
    'Unknown' as region,
    cast(null as string) as city,
    cast(null as string) as postcode,
    false as is_valid_postcode,
    'UNKNOWN' as status,
    timestamp('1900-01-01') as valid_from,
    timestamp('9999-12-31') as valid_to,
    true as is_current
