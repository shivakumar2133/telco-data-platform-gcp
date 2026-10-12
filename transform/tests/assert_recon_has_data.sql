-- NO_DATA means a side of the comparison is missing (e.g. source totals not captured).
-- Not a mismatch, but reconciliation that didn't run is not evidence: warn.
{{ config(severity='warn') }}
select check_id
from {{ ref('recon_results') }}
where
    recon_run_id = (select recon_run_id from {{ ref('recon_results') }} order by recon_run_at desc limit 1)
    and status = 'NO_DATA'
