"""Phase 2 verification: infrastructure exists AND least privilege really holds.

Positive tests prove each service account can do its job.
Negative tests prove it cannot do anything else - the part most projects skip.
All BigQuery checks use dry runs, so this script costs nothing.

Run after: make tf-apply && make secrets-push
Note: new IAM grants can take 1-2 minutes to take effect. If a positive test
fails right after apply, wait and run again.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Callable

from google.api_core import exceptions as gexc
from google.cloud import bigquery, secretmanager, storage

from ingestion.common.config import DATASETS, get_settings
from ingestion.common.gcp_auth import impersonate

DENIED = (gexc.Forbidden, gexc.PermissionDenied, gexc.NotFound, gexc.Unauthorized)
results: list[tuple[str, bool, str]] = []


def expect_ok(name: str, fn: Callable[[], str | None]) -> None:
    try:
        detail = fn() or ""
        results.append((name, True, detail))
    except Exception as exc:  # noqa: BLE001
        results.append((name, False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:110]}"))


def expect_denied(name: str, fn: Callable[[], object]) -> None:
    try:
        fn()
        results.append((name, False, "was ALLOWED - permission is too broad"))
    except DENIED as exc:
        results.append((name, True, f"denied ({exc.code})"))
    except Exception as exc:  # noqa: BLE001
        results.append((name, False, f"unexpected {type(exc).__name__}: {str(exc)[:100]}"))


def main() -> int:
    s = get_settings()
    bq = bigquery.Client(project=s.project_id)
    gcs = storage.Client(project=s.project_id)
    sm = secretmanager.SecretManagerServiceClient()

    # ---- 1. Resources exist and are configured as designed
    def check_bucket() -> str:
        b = gcs.get_bucket(s.lake_bucket)
        assert b.location == s.region.upper(), f"location {b.location}"
        assert b.iam_configuration.uniform_bucket_level_access_enabled, "UBLA off"
        assert b.iam_configuration.public_access_prevention == "enforced", "PAP not enforced"
        return f"{b.name} in {b.location}, uniform access, public access blocked"

    expect_ok("lake bucket", check_bucket)

    for ds in DATASETS:

        def check_ds(ds=ds) -> str:
            d = bq.get_dataset(f"{s.project_id}.{ds}")
            assert d.location.lower() == s.bq_location.lower(), f"location {d.location}"
            expiry = d.default_table_expiration_ms
            return f"location {d.location}" + (
                f", tables expire {expiry // 86400000}d" if expiry else ""
            )

        expect_ok(f"dataset {ds}", check_ds)

    def check_audit() -> str:
        t = bq.get_table(s.table("ops", "load_audit"))
        assert t.time_partitioning and t.time_partitioning.field == "started_at"
        return f"partitioned on started_at, clustered on {t.clustering_fields}"

    expect_ok("ops.load_audit table", check_audit)
    expect_ok("ops.watermarks table", lambda: bq.get_table(s.table("ops", "watermarks")) and "")

    for secret in [
        "oracle-etl-reader-password",
        "mssql-etl-reader-password",
        "postgres-etl-reader-password",
        "tickets-api-key",
    ]:
        expect_ok(
            f"secret {secret} has a value",
            lambda secret=secret: (
                sm.access_secret_version(
                    name=f"projects/{s.project_id}/secrets/{secret}/versions/latest"
                )
                and ""
            ),
        )

    # ---- 2. Least privilege, tested by impersonating each service account
    def clients(sa: str):
        creds = impersonate(s.sa_email(sa))
        return (
            bigquery.Client(project=s.project_id, credentials=creds),
            storage.Client(project=s.project_id, credentials=creds),
            secretmanager.SecretManagerServiceClient(credentials=creds),
        )

    def dry_run(client: bigquery.Client, dataset: str) -> str:
        sql = f"SELECT table_name FROM `{s.project_id}.{dataset}.INFORMATION_SCHEMA.TABLES`"
        job = client.query(
            sql, job_config=bigquery.QueryJobConfig(dry_run=True), location=s.bq_location
        )
        return f"dry run ok ({job.total_bytes_processed or 0} bytes)"

    def create_and_drop(client: bigquery.Client, dataset: str) -> str:
        tid = s.table(dataset, f"_iam_probe_{uuid.uuid4().hex[:8]}")
        client.create_table(bigquery.Table(tid, schema=[bigquery.SchemaField("x", "INT64")]))
        client.delete_table(tid)
        return "created and dropped a probe table"

    def secret(client, name: str):
        return client.access_secret_version(
            name=f"projects/{s.project_id}/secrets/{name}/versions/latest"
        )

    try:
        bq_i, gcs_i, sm_i = clients("ingest")
        bq_t, gcs_t, sm_t = clients("transform")
        bq_b, _gcs_b, sm_b = clients("reporting")
    except Exception as exc:  # noqa: BLE001
        results.append(("impersonation", False, str(exc)[:150]))
    else:

        def ingest_write_lake() -> str:
            blob = gcs_i.bucket(s.lake_bucket).blob(f"tmp/iam_probe_{uuid.uuid4().hex[:8]}.txt")
            blob.upload_from_string("probe")
            blob.delete()
            return "wrote and deleted tmp/ object"

        expect_ok("ingest: write to lake bucket", ingest_write_lake)
        expect_ok("ingest: create table in bronze", lambda: create_and_drop(bq_i, "bronze"))
        expect_ok("ingest: read tickets-api-key", lambda: secret(sm_i, "tickets-api-key") and "ok")
        expect_denied("ingest: create table in gold", lambda: create_and_drop(bq_i, "gold"))

        expect_ok("transform: read bronze", lambda: dry_run(bq_t, "bronze"))
        expect_ok("transform: create table in silver", lambda: create_and_drop(bq_t, "silver"))
        expect_denied("transform: read secrets", lambda: secret(sm_t, "tickets-api-key"))
        expect_denied(
            "transform: write to lake bucket",
            lambda: gcs_t.bucket(s.lake_bucket).blob("tmp/denied.txt").upload_from_string("x"),
        )

        expect_ok("reporting: read gold", lambda: dry_run(bq_b, "gold"))
        expect_denied("reporting: read bronze", lambda: dry_run(bq_b, "bronze"))
        expect_denied("reporting: read secrets", lambda: secret(sm_b, "tickets-api-key"))

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = sum(not ok for _, ok, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
