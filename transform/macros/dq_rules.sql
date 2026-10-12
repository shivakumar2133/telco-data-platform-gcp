{#
  dq_rules(): the data quality rule catalogue. ONE place defines every rule;
  dq_failures, dq_scorecard and dq_rule_catalog are all generated from it.
  Adding a rule = adding one dict here.

  Each rule:
    id              unique rule name
    defect_type     the defect it detects (matches data_generator's defects_manifest.json;
                    none for invariants that should never fail)
    dimension       completeness | uniqueness | validity | consistency | integrity |
                    timeliness | accuracy
    severity        error -> breaching the threshold FAILS the pipeline
                    warn  -> breaching it alerts, the pipeline continues
    max_failure_pct agreed tolerance: % of the population allowed to fail
    object          what is checked (for humans)
    relation        table or sub-query to check
    key             expression that identifies one record (becomes record_key)
    fail_if         condition that makes a record a failure
    scope           optional filter: which records are in the population at all

  Oracle analogy: a table of rules driving dynamic SQL, like a home-grown DQ
  package that loops over a rules table and runs EXECUTE IMMEDIATE per rule -
  except here the SQL is generated at compile time and is reviewable in git.
#}
{% macro dq_rules() %}

  {%- set latest_sla_file -%}
    (select *,
            concat(trim(sla_tier), '/', trim(priority)) as sla_key,
            count(*) over (partition by trim(sla_tier), trim(priority)) as copies_in_file
     from {{ source('bronze', 'files__sla_targets') }}
     where _ingested_at = (select max(_ingested_at) from {{ source('bronze', 'files__sla_targets') }}))
  {%- endset -%}

  {%- set cdr_copies -%}
    (select cdr_id,
            count(*) as copies,
            string_agg(distinct _source_file, ',') as source_files
     from {{ source('bronze', 'files__cdr') }}
     group by cdr_id)
  {%- endset -%}

  {%- set alarm_exports -%}
    (select alarm_id,
            count(distinct _source_file) as export_files,
            string_agg(distinct _source_file, ',') as source_files
     from {{ source('bronze', 'files__alarms') }}
     group by alarm_id)
  {%- endset -%}

  {%- set alarm_file_loads -%}
    (select concat('NMS-EXPORT-', regexp_extract(object_name, r'(\d{8})')) as export_id,
            object_name, status, error_message, started_at
     from {{ source('ops', 'load_audit') }}
     where source_system = 'files' and starts_with(object_name, 'alarms/')
     qualify row_number() over (partition by object_name order by started_at desc) = 1)
  {%- endset -%}

  {#- Every DELIVERED version of an alarm, not just the current one: a re-export can
      correct a bad device_id, but the source still sent bad data once (feedback to its owner) #}
  {%- set alarm_deliveries -%}
    (select a.alarm_id, a.device_id, a._source_file, a.raised_at,
            d.device_id is null as is_unknown_device
     from {{ ref('stg_files__alarms') }} as a
     left join {{ ref('network_devices') }} as d on d.device_id = a.device_id)
  {%- endset -%}

  {%- set customer_matches -%}
    (select *,
            row_number() over (
              partition by lower(trim(first_name)), lower(trim(last_name)),
                           -- people match on date of birth, business contacts on company
                           coalesce(cast(date_of_birth as string), lower(trim(company_name))),
                           upper(replace(postcode, ' ', ''))
              order by created_at, customer_id) as match_rank
     from {{ ref('crm_customers') }})
  {%- endset -%}

  {%- set rules = [

    {'id': 'crm_duplicate_customer', 'defect_type': 'crm_duplicate_customer',
     'dimension': 'uniqueness', 'severity': 'warn', 'max_failure_pct': 1.0,
     'object': 'silver.crm_customers', 'relation': customer_matches, 'key': 'customer_id',
     'scope': 'coalesce(cast(date_of_birth as string), company_name) is not null',
     'fail_if': 'match_rank > 1',
     'description': 'Same person (name + date of birth or company + postcode) under a second customer_id. The newer record is flagged.'},

    {'id': 'crm_null_email', 'defect_type': 'crm_null_email',
     'dimension': 'completeness', 'severity': 'warn', 'max_failure_pct': 2.0,
     'object': 'silver.crm_customers', 'relation': ref('crm_customers'), 'key': 'customer_id',
     'fail_if': 'email is null',
     'description': 'Customer has no email address.'},

    {'id': 'crm_invalid_postcode', 'defect_type': 'crm_invalid_postcode',
     'dimension': 'validity', 'severity': 'warn', 'max_failure_pct': 1.0,
     'object': 'silver.crm_customers', 'relation': ref('crm_customers'), 'key': 'customer_id',
     'fail_if': 'not is_valid_postcode',
     'description': 'Postcode is not a valid UK postcode.'},

    {'id': 'crm_orphan_subscription', 'defect_type': 'crm_orphan_subscription',
     'dimension': 'integrity', 'severity': 'warn', 'max_failure_pct': 1.0,
     'object': 'gold.dim_subscription', 'relation': ref('dim_subscription'), 'key': 'subscription_id',
     'scope': 'subscription_sk <> -1',
     'fail_if': 'is_orphan',
     'description': 'Subscription points to a customer that does not exist in CRM.'},

    {'id': 'billing_revenue_leakage', 'defect_type': 'billing_revenue_leakage',
     'dimension': 'accuracy', 'severity': 'error', 'max_failure_pct': 5.0,
     'object': 'gold.mart_revenue_assurance', 'relation': ref('mart_revenue_assurance'), 'key': 'subscription_id',
     'fail_if': "assurance_status = 'LEAKAGE'",
     'description': 'Rated usage was never billed. Above 5% of subscriptions points to a billing run failure.'},

    {'id': 'billing_header_line_mismatch', 'defect_type': 'billing_header_line_mismatch',
     'dimension': 'consistency', 'severity': 'error', 'max_failure_pct': 2.0,
     'object': 'gold.fct_invoices', 'relation': ref('fct_invoices'), 'key': 'invoice_id',
     'fail_if': 'dq_header_line_mismatch',
     'description': 'Invoice total differs from the sum of its lines.'},

    {'id': 'cdr_duplicate', 'defect_type': 'cdr_duplicate',
     'dimension': 'uniqueness', 'severity': 'warn', 'max_failure_pct': 0.5,
     'object': 'bronze.files__cdr', 'relation': cdr_copies, 'key': 'cdr_id',
     'fail_if': 'copies > 1',
     'description': 'Same cdr_id delivered more than once (Silver keeps one copy).'},

    {'id': 'cdr_late_arrival', 'defect_type': 'cdr_late_arrival',
     'dimension': 'timeliness', 'severity': 'warn', 'max_failure_pct': 1.0,
     'object': 'silver.usage_cdrs', 'relation': ref('usage_cdrs'), 'key': 'cdr_id',
     'fail_if': 'is_late_arrival',
     'description': "Call delivered in a later day's file than the day it happened."},

    {'id': 'cdr_negative_duration', 'defect_type': 'cdr_negative_duration',
     'dimension': 'validity', 'severity': 'error', 'max_failure_pct': 0.1,
     'object': 'silver.usage_cdrs', 'relation': ref('usage_cdrs'), 'key': 'cdr_id',
     'fail_if': 'dq_negative_duration',
     'description': 'Voice call with a negative duration (mediation fault).'},

    {'id': 'cdr_unknown_cell', 'defect_type': 'cdr_unknown_cell',
     'dimension': 'integrity', 'severity': 'error', 'max_failure_pct': 0.5,
     'object': 'gold.fct_calls', 'relation': ref('fct_calls'), 'key': 'cdr_id',
     'fail_if': 'dq_unknown_cell',
     'description': 'Call made on a cell that is not in the network inventory.'},

    {'id': 'alarm_cleared_before_raised', 'defect_type': 'alarm_cleared_before_raised',
     'dimension': 'validity', 'severity': 'warn', 'max_failure_pct': 5.0,
     'object': 'silver.network_alarms', 'relation': ref('network_alarms'), 'key': 'alarm_id',
     'fail_if': 'dq_cleared_before_raised',
     'description': 'Alarm cleared before it was raised (clock or export fault).'},

    {'id': 'alarm_unknown_device', 'defect_type': 'alarm_unknown_device',
     'dimension': 'integrity', 'severity': 'warn', 'max_failure_pct': 5.0,
     'object': 'silver.stg_files__alarms (every delivery)', 'relation': alarm_deliveries, 'key': 'alarm_id',
     'fail_if': 'is_unknown_device',
     'description': 'Alarm delivered with a device that is not in the network inventory (in any export).'},

    {'id': 'alarm_reexported', 'defect_type': 'alarm_reexported',
     'dimension': 'uniqueness', 'severity': 'warn', 'max_failure_pct': 5.0,
     'object': 'bronze.files__alarms', 'relation': alarm_exports, 'key': 'alarm_id',
     'fail_if': 'export_files > 1',
     'description': 'Same alarm sent in more than one daily export (Silver keeps one).'},

    {'id': 'alarm_record_count_mismatch', 'defect_type': 'alarm_record_count_mismatch',
     'dimension': 'consistency', 'severity': 'warn', 'max_failure_pct': 5.0,
     'object': 'ops.load_audit', 'relation': alarm_file_loads, 'key': 'export_id',
     'fail_if': "status = 'REJECTED'",
     'description': 'Alarm export rejected: header record_count did not match its content (file quarantined).'},

    {'id': 'ticket_resolved_without_date', 'defect_type': 'ticket_resolved_without_date',
     'dimension': 'completeness', 'severity': 'warn', 'max_failure_pct': 1.0,
     'object': 'silver.service_tickets', 'relation': ref('service_tickets'), 'key': 'ticket_id',
     'fail_if': 'dq_resolved_without_date',
     'description': 'Ticket marked RESOLVED without a resolved_at time (SLA cannot be measured).'},

    {'id': 'ticket_unknown_customer', 'defect_type': 'ticket_unknown_customer',
     'dimension': 'integrity', 'severity': 'warn', 'max_failure_pct': 1.0,
     'object': 'gold.fct_tickets', 'relation': ref('fct_tickets'), 'key': 'ticket_id',
     'fail_if': 'dq_unknown_customer',
     'description': 'Ticket raised for a customer that does not exist in CRM.'},

    {'id': 'sla_trailing_whitespace', 'defect_type': 'sla_trailing_whitespace',
     'dimension': 'validity', 'severity': 'warn', 'max_failure_pct': 0.0,
     'object': 'bronze.files__sla_targets (latest file)', 'relation': latest_sla_file, 'key': 'sla_key',
     'fail_if': 'sla_tier != trim(sla_tier) or priority != trim(priority)',
     'description': 'Leading/trailing spaces in the workbook (would break joins on tier).'},

    {'id': 'sla_text_in_numeric', 'defect_type': 'sla_text_in_numeric',
     'dimension': 'validity', 'severity': 'warn', 'max_failure_pct': 0.0,
     'object': 'bronze.files__sla_targets (latest file)', 'relation': latest_sla_file, 'key': 'sla_key',
     'fail_if': '(response_hrs is not null and safe_cast(response_hrs as float64) is null) or (resolution_hrs is not null and safe_cast(resolution_hrs as float64) is null)',
     'description': "Hours typed as text (e.g. '24 hrs') in a numeric column."},

    {'id': 'sla_inconsistent_percentage', 'defect_type': 'sla_inconsistent_percentage',
     'dimension': 'consistency', 'severity': 'warn', 'max_failure_pct': 0.0,
     'object': 'bronze.files__sla_targets (latest file)', 'relation': latest_sla_file, 'key': 'sla_key',
     'fail_if': 'safe_cast(availability_target as float64) <= 1',
     'description': 'Availability written as a fraction (0.999) instead of a percentage (99.9).'},

    {'id': 'sla_duplicate_row', 'defect_type': 'sla_duplicate_row',
     'dimension': 'uniqueness', 'severity': 'warn', 'max_failure_pct': 0.0,
     'object': 'bronze.files__sla_targets (latest file)', 'relation': latest_sla_file, 'key': 'sla_key',
     'fail_if': 'copies_in_file > 1',
     'description': 'Same tier/priority row appears more than once in the workbook.'},

    {'id': 'inv_invoice_due_before_issue', 'defect_type': none,
     'dimension': 'consistency', 'severity': 'error', 'max_failure_pct': 0.0,
     'object': 'silver.billing_invoices', 'relation': ref('billing_invoices'), 'key': 'invoice_id',
     'fail_if': 'due_date < invoice_date',
     'description': 'Invariant: an invoice cannot be due before it is issued.'},

    {'id': 'inv_paid_more_than_invoiced', 'defect_type': none,
     'dimension': 'accuracy', 'severity': 'error', 'max_failure_pct': 0.0,
     'object': 'gold.fct_invoices', 'relation': ref('fct_invoices'), 'key': 'invoice_id',
     'fail_if': 'paid_amount > total_amount',
     'description': 'Invariant: payments never exceed the invoice total (would indicate double-counted payments).'},

    {'id': 'inv_negative_charge', 'defect_type': none,
     'dimension': 'validity', 'severity': 'error', 'max_failure_pct': 0.0,
     'object': 'gold.fct_calls', 'relation': ref('fct_calls'), 'key': 'cdr_id',
     'fail_if': 'charge_amount < 0',
     'description': 'Invariant: rating never produces a negative charge.'},

    {'id': 'inv_ticket_resolved_before_opened', 'defect_type': none,
     'dimension': 'consistency', 'severity': 'error', 'max_failure_pct': 0.0,
     'object': 'silver.service_tickets', 'relation': ref('service_tickets'), 'key': 'ticket_id',
     'fail_if': 'resolved_at < opened_at',
     'description': 'Invariant: a ticket cannot be resolved before it was opened.'},

  ] -%}

  {{ return(rules) }}
{% endmacro %}


{# Run timestamp shared by every DQ / reconciliation row written in one dbt invocation #}
{% macro dq_run_at() -%}
    timestamp('{{ run_started_at.strftime("%Y-%m-%d %H:%M:%S") }}')
{%- endmacro %}

{% macro sql_string(value) -%}
    {%- if value is none -%}cast(null as string){%- else -%}'{{ value | replace("'", "\\'") }}'{%- endif -%}
{%- endmacro %}
