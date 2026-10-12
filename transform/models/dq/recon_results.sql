{#
  Cross-layer reconciliation: does every row and every pound survive each hop?

    source_to_bronze   source row count (captured at extraction) = distinct keys in Bronze
    audit_to_bronze    rows the extractor says it loaded (ops.load_audit) = rows in Bronze
    file_header        alarm exports: header record_count = alarms in the file
    bronze_to_silver   distinct Bronze keys = Silver rows (dedup lost nothing)
    silver_to_gold     Silver rows and amounts = Gold fact rows and amounts (no fan-out)
    source_to_silver   source money totals = Silver money totals, to the penny

  Appended every run (history = audit evidence). status: PASS | FAIL | NO_DATA.
  Oracle analogy: the control-total report you run after a nightly load, persisted.
#}
{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    full_refresh=false,
    partition_by={'field': 'recon_run_date', 'data_type': 'date'},
) }}

{#- (source system, source table, bronze table, silver model, key, amount column) -#}
{%- set db_entities = [
    ('mssql', 'customers', 'mssql__customers', 'crm_customers', 'customer_id', none),
    ('mssql', 'products', 'mssql__products', 'crm_products', 'product_id', none),
    ('mssql', 'subscriptions', 'mssql__subscriptions', 'crm_subscriptions', 'subscription_id', none),
    ('oracle', 'billing_accounts', 'oracle__billing_accounts', 'billing_accounts', 'account_id', none),
    ('oracle', 'invoices', 'oracle__invoices', 'billing_invoices', 'invoice_id', 'total_amount'),
    ('oracle', 'invoice_lines', 'oracle__invoice_lines', 'billing_invoice_lines', 'line_id', 'amount'),
    ('oracle', 'payments', 'oracle__payments', 'billing_payments', 'payment_id', 'amount'),
    ('postgres', 'sites', 'postgres__sites', 'network_sites', 'site_id', none),
    ('postgres', 'cells', 'postgres__cells', 'network_cells', 'cell_id', none),
    ('postgres', 'devices', 'postgres__devices', 'network_devices', 'device_id', none),
] -%}
{#- (audit source_system, audit object prefix, bronze table, silver model, key) -#}
{%- set feed_entities = [
    ('files', 'cdr', 'files__cdr', 'usage_cdrs', 'cdr_id'),
    ('files', 'alarms', 'files__alarms', 'network_alarms', 'alarm_id'),
    ('api', 'tickets', 'api__tickets', 'service_tickets', 'ticket_id'),
] -%}
{#- (silver model, gold fact, amount column in silver, amount column in gold) -#}
{%- set gold_facts = [
    ('usage_cdrs', 'fct_calls', 'charge_amount', 'charge_amount'),
    ('billing_invoice_lines', 'fct_invoice_lines', 'amount', 'amount'),
    ('billing_invoices', 'fct_invoices', 'total_amount', 'total_amount'),
    ('service_tickets', 'fct_tickets', none, none),
    ('network_alarms', 'fct_network_faults', none, none),
] -%}

with source_totals as (
    select source_system, object_name, row_count, sum_amount
    from {{ source('ops', 'source_control_totals') }}
    qualify row_number() over (partition by source_system, object_name order by captured_at desc) = 1
),

audit_totals as (
    select
        source_system,
        -- DB objects are logged by table name, files as '<object>/<file name>'
        split(object_name, '/')[offset(0)] as object_name,
        sum(loaded_row_count) as loaded_rows
    from {{ source('ops', 'load_audit') }}
    where status = 'SUCCESS'
    group by 1, 2
),

checks as (

  {#- 1. source -> bronze: rows at source = distinct keys in Bronze #}
  {% for system, tbl, bronze, silver, key, amount in db_entities %}
    select 'source_to_bronze' as check_type, '{{ system }}.{{ tbl }}' as entity, 'row_count' as measure,
           cast((select row_count from source_totals
                 where source_system = '{{ system }}' and object_name = '{{ tbl }}') as numeric) as expected,
           cast((select count(distinct {{ key }}) from {{ source('bronze', bronze) }}) as numeric) as actual
    union all
  {% endfor %}

  {#- 2. audit -> bronze: what the extractor logged as loaded = what Bronze holds #}
  {% for system, tbl, bronze, silver, key, amount in db_entities %}
    select 'audit_to_bronze', 'bronze.{{ bronze }}', 'row_count',
           cast((select loaded_rows from audit_totals
                 where source_system = '{{ system }}' and object_name = '{{ tbl }}') as numeric),
           cast((select count(*) from {{ source('bronze', bronze) }}) as numeric)
    union all
  {% endfor %}
  {% for system, obj, bronze, silver, key in feed_entities %}
    select 'audit_to_bronze', 'bronze.{{ bronze }}', 'row_count',
           cast((select loaded_rows from audit_totals
                 where source_system = '{{ system }}' and object_name = '{{ obj }}') as numeric),
           cast((select count(*) from {{ source('bronze', bronze) }}) as numeric)
    union all
  {% endfor %}

  {#- 3. file control totals: every loaded alarm export matches its own header #}
    select 'file_header', 'bronze.files__alarms', 'files_with_header_mismatch',
           cast(0 as numeric),
           cast((select count(*) from (
                    select _source_file
                    from {{ source('bronze', 'files__alarms') }}
                    group by _source_file
                    having count(*) != max(cast(export_record_count as int64)))) as numeric)
    union all

  {#- 4. bronze -> silver: every distinct Bronze key is one Silver row #}
  {% for system, tbl, bronze, silver, key, amount in db_entities %}
    select 'bronze_to_silver', 'silver.{{ silver }}', 'row_count',
           cast((select count(distinct {{ key }}) from {{ source('bronze', bronze) }}) as numeric),
           cast((select count(*) from {{ ref(silver) }}) as numeric)
    union all
  {% endfor %}
  {% for system, obj, bronze, silver, key in feed_entities %}
    select 'bronze_to_silver', 'silver.{{ silver }}', 'row_count',
           cast((select count(distinct {{ key }}) from {{ source('bronze', bronze) }}) as numeric),
           cast((select count(*) from {{ ref(silver) }}) as numeric)
    union all
  {% endfor %}

  {#- 5. silver -> gold: rows and money survive the star schema joins #}
  {% for silver, fact, silver_amount, gold_amount in gold_facts %}
    select 'silver_to_gold', 'gold.{{ fact }}', 'row_count',
           cast((select count(*) from {{ ref(silver) }}) as numeric),
           cast((select count(*) from {{ ref(fact) }}) as numeric)
    union all
    {% if silver_amount %}
    select 'silver_to_gold', 'gold.{{ fact }}', 'sum_{{ gold_amount }}',
           cast((select sum({{ silver_amount }}) from {{ ref(silver) }}) as numeric),
           cast((select sum({{ gold_amount }}) from {{ ref(fact) }}) as numeric)
    union all
    {% endif %}
  {% endfor %}

  {#- 6. source -> silver: money at source = money in Silver, to the penny #}
  {% for system, tbl, bronze, silver, key, amount in db_entities if amount %}
    select 'source_to_silver', 'silver.{{ silver }}', 'sum_{{ amount }}',
           cast((select sum_amount from source_totals
                 where source_system = '{{ system }}' and object_name = '{{ tbl }}') as numeric),
           cast((select sum({{ amount }}) from {{ ref(silver) }}) as numeric)
    {% if not loop.last %}union all{% endif %}
  {% endfor %}
)

select
    '{{ invocation_id }}' as recon_run_id,
    {{ dq_run_at() }} as recon_run_at,
    date({{ dq_run_at() }}) as recon_run_date,
    concat(check_type, ':', entity, ':', measure) as check_id,
    check_type,
    entity,
    measure,
    expected,
    actual,
    actual - expected as difference,
    case
        when expected is null or actual is null then 'NO_DATA'
        when expected = actual then 'PASS'
        else 'FAIL'
    end as status
from checks
