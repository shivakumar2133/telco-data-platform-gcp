{#
  Governance applied by dbt on every build (Phase 8).

  Why dbt and not Terraform? Gold tables are rebuilt with CREATE OR REPLACE, which
  drops row access policies, table grants and policy tags. Whatever rebuilds the
  table must re-apply them in the same run, so they live next to the model.

  Entitlements are configuration (dbt_project.yml vars), not code:
    rls_full_access: service accounts that see every row
    rls_regions:     region -> service accounts that see only that region
  Plus the data steward (your own account, env DATA_STEWARD="user:you@...").
#}

{% macro sa_principal(name) -%}
    serviceAccount:sa-{{ name }}@{{ target.project }}.iam.gserviceaccount.com
{%- endmacro %}

{% macro full_access_principals() %}
    {% set out = [] %}
    {% for sa in var('rls_full_access') %}{% do out.append(sa_principal(sa)) %}{% endfor %}
    {% set steward = env_var('DATA_STEWARD', '') %}
    {% if steward %}{% do out.append(steward) %}{% endif %}
    {{ return(out) }}
{% endmacro %}

{# Every principal with a regional entitlement (used for table grants) #}
{% macro regional_principals() %}
    {% set out = [] %}
    {% for region, sas in var('rls_regions').items() %}
        {% for sa in sas %}{% do out.append(sa_principal(sa)) %}{% endfor %}
    {% endfor %}
    {{ return(out | unique | list) }}
{% endmacro %}

{% macro _grantees(principals) -%}
    {%- for p in principals %}"{{ p }}"{% if not loop.last %}, {% endif %}{% endfor -%}
{%- endmacro %}

{#
  row_access_policies(): post-hook for tables with a region column.
  Anyone not named in a policy sees ZERO rows - including project owners - so the
  pipeline itself (sa-transform) and the dashboards (sa-reporting) get a TRUE filter.
  Oracle analogy: a VPD (DBMS_RLS) policy that appends WHERE region = ... per user.
#}
{% macro row_access_policies(region_column='region') %}
    {%- if target.type != 'bigquery' -%}
        {{ return('select 1') }}
    {%- endif -%}
    {%- set statements = [] -%}
    {%- do statements.append(
        "create or replace row access policy all_regions on " ~ this
        ~ " grant to (" ~ _grantees(full_access_principals()) ~ ") filter using (true)"
    ) -%}
    {%- for region, sas in var('rls_regions').items() -%}
        {%- set name = 'region_' ~ modules.re.sub('[^a-z0-9]+', '_', region | lower) -%}
        {%- set principals = [] -%}
        {%- for sa in sas %}{% do principals.append(sa_principal(sa)) %}{% endfor -%}
        {%- do statements.append(
            "create or replace row access policy " ~ name ~ " on " ~ this
            ~ " grant to (" ~ _grantees(principals) ~ ")"
            ~ " filter using (" ~ region_column ~ " = '" ~ region ~ "')"
        ) -%}
    {%- endfor -%}
    {{ return(statements | join(';\n')) }}
{% endmacro %}

{#
  on-run-start check: refuse to build if the policy tag ids are missing, instead of
  silently publishing personal data without column-level security.
#}
{% macro check_governance_env() %}
    {%- if target.type == 'bigquery' and execute -%}
        {%- set missing = [] -%}
        {%- for tag in ['EMAIL', 'PHONE', 'NAME', 'BIRTH_DATE', 'POSTCODE', 'RAW_RECORD'] -%}
            {%- set value = env_var('DBT_POLICY_TAG_' ~ tag, '') -%}
            {%- if not value.startswith('projects/') -%}{% do missing.append('DBT_POLICY_TAG_' ~ tag) %}{%- endif -%}
        {%- endfor -%}
        {%- if missing -%}
            {{ exceptions.raise_compiler_error(
                "Policy tag ids not set: " ~ missing | join(', ')
                ~ ". Run `make governance-env` after `make tf-apply`.") }}
        {%- endif -%}
    {%- endif -%}
    select 1 as governance_env_ok
{% endmacro %}
