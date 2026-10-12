from quality.dq_compare import alarm_files, compare, export_date, overall_recall, render

MANIFEST = {
    "crm_null_email": {"ids": ["CUS1", "CUS2", "CUS3"]},
    "alarm_unknown_device": {"ids": ["ALM2026090700001", "ALM2026090800001"]},
    "alarm_reexported": {"ids": ["ALM2026090600009"]},
    "alarm_record_count_mismatch": {"ids": ["NMS-EXPORT-20260907"]},
    "sla_duplicate_row": {"ids": ["Premium/P1"]},
}


def by_type(results):
    return {r.defect_type: r for r in results}


def test_everything_detected_is_full_recall():
    detected = {k: set(v["ids"]) for k, v in MANIFEST.items()}
    results = compare(MANIFEST, detected)
    assert all(r.status == "OK" for r in results)
    assert overall_recall(results) == 1.0


def test_missing_records_are_listed():
    r = by_type(compare(MANIFEST, {"crm_null_email": {"CUS1"}}))["crm_null_email"]
    assert r.detected == 1 and r.missed == ["CUS2", "CUS3"] and r.status == "MISSED"


def test_extra_findings_lower_precision_not_recall():
    detected = {"crm_null_email": {"CUS1", "CUS2", "CUS3", "CUS9"}}
    r = by_type(compare(MANIFEST, detected))["crm_null_email"]
    assert r.recall == 1.0 and r.extra == 1 and r.precision == 0.75


def test_alarm_in_rejected_file_counts_as_quarantined():
    detected = {"alarm_unknown_device": {"ALM2026090800001"}}
    r = by_type(compare(MANIFEST, detected, rejected_exports={"NMS-EXPORT-20260907"}))
    assert r["alarm_unknown_device"].quarantined == 1
    assert r["alarm_unknown_device"].status == "OK"


def test_reexport_into_rejected_next_day_file_is_quarantined():
    assert alarm_files("alarm_reexported", "ALM2026090600009") == {"20260906", "20260907"}
    assert alarm_files("alarm_unknown_device", "ALM2026090600009") == {"20260906"}
    r = by_type(compare(MANIFEST, {}, rejected_exports={"NMS-EXPORT-20260907"}))
    assert r["alarm_reexported"].quarantined == 1


def test_quarantine_does_not_hide_non_alarm_defects():
    r = by_type(compare(MANIFEST, {}, rejected_exports={"NMS-EXPORT-20260907"}))
    assert r["crm_null_email"].quarantined == 0
    assert r["alarm_record_count_mismatch"].missed == ["NMS-EXPORT-20260907"]


def test_fixed_at_source():
    detected = {"crm_null_email": {"CUS1", "CUS2"}}
    r = by_type(compare(MANIFEST, detected, fixed_at_source={"crm_null_email": {"CUS3"}}))
    assert r["crm_null_email"].fixed_at_source == 1 and r["crm_null_email"].status == "OK"


def test_defect_without_rule_is_flagged():
    r = by_type(compare(MANIFEST, {}))["sla_duplicate_row"]
    assert r.status == "NO RULE" and r.missed == ["Premium/P1"]


def test_export_date_and_render():
    assert export_date("NMS-EXPORT-20260907") == "20260907"
    text = render(compare(MANIFEST, {}), markdown=True)
    assert text.splitlines()[0].startswith("| defect |") and "TOTAL" in text
