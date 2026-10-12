{#
  Latest reconciliation run, one row per check: the "does every row and pound arrive?"
  table on the data quality page. A view; history stays in recon_results.
#}
{{ config(materialized='view') }}

select
    recon_run_at,
    check_type,
    entity,
    measure,
    expected,
    actual,
    difference,
    status
from {{ ref('recon_results') }}
where recon_run_id = (select recon_run_id from {{ ref('recon_results') }} order by recon_run_at desc limit 1)
