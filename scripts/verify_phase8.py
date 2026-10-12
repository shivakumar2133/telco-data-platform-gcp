"""Phase 8 verification: who can see what, tested by acting as each identity.

  column-level  policy tags are attached to the PII columns (Silver, Gold, DQ quarantine)
  masking       you (data steward) see real values; sa-reporting / sa-analyst see masked ones
  row-level     sa-analyst sees only North West rows; sa-reporting sees every region
  table-level   sa-analyst can't read facts; sa-ingest can't read Gold at all
  audit         who queried tables holding personal data in the last 7 days

Run after: make tf-apply governance-env dbt-build. New grants can take 1-2 minutes.
Queries read a few MB (the cheapest possible columns), well inside the free tier.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable

from google.api_core import exceptions as gexc
from google.cloud import bigquery

from ingestion.common.config import get_settings
from ingestion.common.gcp_auth import impersonate

DENIED = (gexc.Forbidden, gexc.PermissionDenied, gexc.NotFound)
results: list[tuple[str, bool, str]] = []
REGION = "North West"  # must match rls_regions in transform/dbt_project.yml

# (dataset.table, column, env var holding the expected policy tag)
TAGGED = [
    ("gold.dim_customer", "email", "DBT_POLICY_TAG_EMAIL"),
    ("gold.dim_customer", "postcode", "DBT_POLICY_TAG_POSTCODE"),
    ("gold.dim_subscription", "msisdn", "DBT_POLICY_TAG_PHONE"),
    ("silver.crm_customers", "date_of_birth", "DBT_POLICY_TAG_BIRTH_DATE"),
    ("silver.crm_customers", "last_name", "DBT_POLICY_TAG_NAME"),
    ("silver.crm_customers_snapshot", "email", "DBT_POLICY_TAG_EMAIL"),
    ("silver.usage_cdrs", "msisdn_a", "DBT_POLICY_TAG_PHONE"),
    ("ops.dq_failures", "record_json", "DBT_POLICY_TAG_RAW_RECORD"),
]


def check(name: str, fn: Callable[[], str | None]) -> None:
    try:
        results.append((name, True, fn() or ""))
    except AssertionError as exc:
        results.append((name, False, str(exc)))
    except Exception as exc:  # noqa: BLE001 - report, don't crash
        results.append((name, False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:120]}"))


def denied(name: str, fn: Callable[[], object]) -> None:
    try:
        fn()
        results.append((name, False, "was ALLOWED"))
    except DENIED as exc:
        results.append((name, True, f"denied ({exc.code})"))
    except Exception as exc:  # noqa: BLE001
        results.append((name, False, f"unexpected {type(exc).__name__}: {str(exc)[:100]}"))


def main() -> int:
    s = get_settings()
    p = s.project_id

    def client(sa: str | None) -> bigquery.Client:
        creds = impersonate(s.sa_email(sa)) if sa else None
        return bigquery.Client(project=p, location=s.bq_location, credentials=creds)

    me, rep, ana, ing = client(None), client("reporting"), client("analyst"), client("ingest")

    def rows(c: bigquery.Client, sql: str) -> list:
        return list(c.query(sql).result())

    # ---- 1. policy tags are attached
    for table, column, env in TAGGED:

        def has_tag(table=table, column=column, env=env) -> str:
            expected = os.environ.get(env, "")
            assert expected.startswith("projects/"), f"{env} not set - run make governance-env"
            field = next(f for f in me.get_table(f"{p}.{table}").schema if f.name == column)
            names = list(field.policy_tags.names) if field.policy_tags else []
            assert names == [expected], f"policy tags {names or 'none'}"
            return f"tagged {env.removeprefix('DBT_POLICY_TAG_').lower()}"

        check(f"{table}.{column} has a policy tag", has_tag)

    # ---- 2. dynamic masking: same customer, three identities
    sample_sql = f"""
        select customer_id, email, postcode, last_name from `{p}.gold.dim_customer`
        where is_current and region = '{REGION}' and email is not null and postcode is not null
        order by customer_id limit 1"""
    raw = rows(me, sample_sql)
    if not raw:
        # zero rows for the owner = not in any row access policy
        results.append(("data steward sees real PII", False, "no rows - is DATA_STEWARD set?"))
    else:
        r = raw[0]
        check("data steward sees real PII", lambda: f"{r.customer_id}: {r.email}, {r.postcode}")
        for label, c in (("sa-reporting", rep), ("sa-analyst", ana)):

            def masked(c=c) -> str:
                m = rows(
                    c,
                    f"select email, postcode, last_name from `{p}.gold.dim_customer` "
                    f"where customer_id = '{r.customer_id}' and is_current",
                )[0]
                domain = r.email.split("@")[1]
                assert m.email != r.email and m.email.endswith(domain), f"email {m.email}"
                assert m.postcode != r.postcode and m.postcode[:4] == r.postcode[:4], m.postcode
                assert m.last_name != r.last_name, "last_name not hashed"
                return f"email {m.email}, postcode {m.postcode}, last_name {m.last_name[:12]}..."

            check(f"{label} sees masked PII", masked)

    def quarantine_hidden() -> str:
        n = rows(rep, f"select countif(record_json is not null) n from `{p}.ops.dq_failures`")[0].n
        assert n == 0, f"{n} raw records visible"
        return "record_json is NULL for masked readers"

    check("sa-reporting can't read quarantined records", quarantine_hidden)

    # ---- 3. row-level security
    count_sql = f"select count(*) n from `{p}.gold.dim_customer`"

    def reporting_all_rows() -> str:
        mine, theirs = rows(me, count_sql)[0].n, rows(rep, count_sql)[0].n
        assert mine == theirs > 0, f"steward {mine} vs reporting {theirs}"
        return f"{theirs:,} rows (all regions)"

    check("sa-reporting sees every region", reporting_all_rows)

    for table in ("dim_customer", "dim_cell", "mart_cell_daily"):

        def one_region(table=table) -> str:
            got = rows(ana, f"select region, count(*) n from `{p}.gold.{table}` group by 1")
            regions = {x.region for x in got}
            assert regions == {REGION}, f"regions visible: {sorted(regions)}"
            return f"{sum(x.n for x in got):,} rows, {REGION} only"

        check(f"sa-analyst: {table} filtered to its region", one_region)

    # ---- 4. table/dataset level
    def probe(c: bigquery.Client, table: str) -> Callable[[], object]:
        return lambda: rows(c, f"select 1 from `{p}.{table}` limit 1")

    denied("sa-analyst: read gold.fct_calls", probe(ana, "gold.fct_calls"))
    denied("sa-analyst: read silver", probe(ana, "silver.crm_customers"))
    denied("sa-ingest: read gold.dim_customer", probe(ing, "gold.dim_customer"))

    # ---- 5. audit: who touched personal data (from BigQuery's own job history)
    def audit() -> str:
        got = rows(
            me,
            f"""
            select user_email, count(*) as queries
            from `region-{s.bq_location.lower()}`.INFORMATION_SCHEMA.JOBS_BY_PROJECT,
                 unnest(referenced_tables) as t
            where creation_time > timestamp_sub(current_timestamp(), interval 7 day)
              and t.table_id in ('dim_customer', 'crm_customers', 'crm_customers_snapshot',
                                 'dim_subscription', 'dq_failures')
            group by 1 order by 2 desc""",
        )
        return "; ".join(f"{x.user_email.split('@')[0]}={x.queries}" for x in got)

    check("audit: PII table access (7 days)", audit)

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    n_failed = sum(not ok for _, ok, _ in results)
    print(f"\n{len(results) - n_failed}/{len(results)} checks passed")
    return 1 if n_failed else 0


if __name__ == "__main__":
    sys.exit(main())
