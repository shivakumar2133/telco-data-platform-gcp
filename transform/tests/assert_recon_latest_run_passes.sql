-- Reconciliation gate: any FAIL in the latest run stops the pipeline.
select check_id, expected, actual, difference
from {{ ref('recon_results') }}
where
    recon_run_id = (select recon_run_id from {{ ref('recon_results') }} order by recon_run_at desc limit 1)
    and status = 'FAIL'
