-- CRM customers: clean and standardise. One row per extracted VERSION (no dedup here).
with source as (
    select * from {{ source('bronze', 'mssql__customers') }}
),

cleaned as (
    select
        customer_id,
        segment,
        initcap(trim(first_name)) as first_name,   -- duplicate records were keyed in upper case
        initcap(trim(last_name)) as last_name,
        nullif(trim(company_name), '') as company_name,
        lower(trim(email)) as email,
        msisdn,
        date_of_birth,
        trim(address_line1) as address_line1,
        trim(city) as city,
        upper(trim(postcode)) as postcode,
        region,
        status,
        created_at,
        updated_at,
        _run_id,
        _ingested_at
    from source
)

select
    *,
    coalesce(regexp_contains(email, r'^[^@\s]+@[^@\s]+\.[^@\s]+$'), false) as is_valid_email,
    coalesce(
        regexp_contains(postcode, r'^[A-Z]{1,2}[0-9][A-Z0-9]? ?[0-9][A-Z]{2}$'), false
    ) as is_valid_postcode
from cleaned
