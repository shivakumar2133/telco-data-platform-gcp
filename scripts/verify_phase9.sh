#!/usr/bin/env bash
# Phase 9 verification: keyless CI/CD is wired up end to end.
#   GCP side   : WIF pool + provider restricted to this repo; who may act as whom
#   GitHub side: repository variables present; latest workflow runs green
# Needs gcloud (your login) and gh (gh auth login). Costs nothing.
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
P="$GCP_PROJECT_ID"
pass=0; fail=0
ok()  { printf 'PASS  %-52s %s\n' "$1" "$2"; pass=$((pass+1)); }
bad() { printf 'FAIL  %-52s %s\n' "$1" "$2"; fail=$((fail+1)); }
check() { local name="$1" detail="$2"; shift 2; if "$@" >/dev/null 2>&1; then ok "$name" "$detail"; else bad "$name" "$detail"; fi; }

cond=$(gcloud iam workload-identity-pools providers describe github --project "$P" \
  --location global --workload-identity-pool github-actions --format 'value(attributeCondition)' 2>/dev/null)
repo=$(grep github_repository infra/terraform/envs/dev.tfvars | cut -d'"' -f2)
[[ "$cond" == *"$repo"* ]] && ok "WIF provider only trusts $repo" "$cond" || bad "WIF provider condition" "${cond:-not found}"

cicd_policy=$(gcloud iam service-accounts get-iam-policy "sa-cicd@$P.iam.gserviceaccount.com" --format json 2>/dev/null)
[[ "$cicd_policy" == *"attribute.repository/$repo"* ]] && ok "repo workflows may act as sa-cicd" "workloadIdentityUser" || bad "sa-cicd binding" "missing"

tr_policy=$(gcloud iam service-accounts get-iam-policy "sa-transform@$P.iam.gserviceaccount.com" --format json 2>/dev/null)
[[ "$tr_policy" == *"attribute.is_main/true"* ]] && ok "only main may act as sa-transform" "workloadIdentityUser" || bad "sa-transform binding" "missing"
[[ "$tr_policy" != *"attribute.repository/"* ]] && ok "pull requests can't act as sa-transform" "no repo-wide binding" || bad "sa-transform too broad" "repo-wide binding found"

roles=$(gcloud projects get-iam-policy "$P" --flatten 'bindings[].members' \
  --filter "bindings.members:sa-cicd@" --format 'value(bindings.role)' 2>/dev/null)
[[ "$roles" != *"roles/viewer"* && "$roles" != *"roles/editor"* && "$roles" != *"roles/owner"* ]] \
  && ok "sa-cicd has no basic role (no data access)" "$(echo "$roles" | wc -l) metadata roles" \
  || bad "sa-cicd has a basic role" "$roles"

keys=$(gcloud iam service-accounts keys list --iam-account "sa-cicd@$P.iam.gserviceaccount.com" \
  --managed-by user --format 'value(name)' 2>/dev/null | wc -l)
[[ "$keys" -eq 0 ]] && ok "sa-cicd has no JSON keys" "keyless" || bad "sa-cicd has user-managed keys" "$keys"

vars=$(gh variable list --json name --jq '.[].name' 2>/dev/null)
for v in GCP_PROJECT_ID WIF_PROVIDER CICD_SA TRANSFORM_SA DEVELOPER_EMAIL DATA_STEWARD DBT_POLICY_TAG_EMAIL; do
  [[ "$vars" == *"$v"* ]] && ok "GitHub variable $v" "set" || bad "GitHub variable $v" "missing - make github-vars"
done

for wf in ci.yml terraform-plan.yml deploy-dbt.yml; do
  res=$(gh run list --workflow "$wf" --limit 1 --json conclusion,headBranch,event \
    --jq '.[0] | "\(.conclusion) (\(.event) on \(.headBranch))"' 2>/dev/null)
  [[ "$res" == success* ]] && ok "latest $wf run" "$res" || bad "latest $wf run" "${res:-no runs yet}"
done

echo; echo "$pass/$((pass+fail)) checks passed"
[[ $fail -eq 0 ]]
