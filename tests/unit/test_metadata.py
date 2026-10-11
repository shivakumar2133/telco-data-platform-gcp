from datetime import UTC, datetime

import pandas as pd

from ingestion.common.metadata import AuditRecord, LocalMetaStore, frame_checksum


def test_checksum_ignores_row_order_but_not_content():
    a = pd.DataFrame({"id": [1, 2, 3], "amt": [10.0, 20.0, 30.0]})
    shuffled = a.sample(frac=1, random_state=1)
    changed = a.assign(amt=[10.0, 20.0, 30.01])
    assert frame_checksum(a) == frame_checksum(shuffled)
    assert frame_checksum(a) != frame_checksum(changed)


def test_latest_watermark_wins(tmp_path):
    m = LocalMetaStore(tmp_path)
    m.set_watermark("oracle", "invoices", "updated_at", datetime(2026, 9, 1, tzinfo=UTC))
    m.set_watermark("oracle", "invoices", "updated_at", datetime(2026, 10, 1, tzinfo=UTC))
    assert m.get_watermarks()[("oracle", "invoices")] == datetime(2026, 10, 1, tzinfo=UTC)


def test_processed_files_only_counts_success(tmp_path):
    m = LocalMetaStore(tmp_path)
    ok = AuditRecord("r", "files", "cdr/a.csv", "FILE", source_checksum="aaa").finish("SUCCESS")
    bad = AuditRecord("r", "files", "cdr/b.csv", "FILE", source_checksum="bbb").finish("REJECTED")
    m.write_audit(ok)
    m.write_audit(bad)
    assert m.processed_file_checksums() == {"aaa"}
