"""Compare what the DQ rules found with what the data generator injected.

Pure logic (no BigQuery), so it is unit-tested. quality/dq_report.py feeds it.

A defect injected into the source can end up in four places:
  detected         a DQ rule flagged exactly that record                    -> caught
  quarantined      its file was rejected at ingestion (never reached BigQuery) -> caught earlier
  fixed_at_source  the source corrected it before we looked (e.g. an email
                   was filled in by simulate_changes)                       -> nothing to catch
  missed           none of the above                                         -> a gap in our checks
Recall = (detected + quarantined + fixed_at_source) / injected. The goal is 100%.
Anything a rule flagged that was NOT injected is "extra" (precision < 100%).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

# The rejected-file check itself; its own ids are export ids, not alarm ids
FILE_LEVEL_DEFECTS = {"alarm_record_count_mismatch"}


@dataclass
class DefectResult:
    defect_type: str
    injected: int
    detected: int = 0
    quarantined: int = 0
    fixed_at_source: int = 0
    extra: int = 0
    has_rule: bool = True
    missed: list[str] = field(default_factory=list)

    @property
    def recall(self) -> float:
        caught = self.detected + self.quarantined + self.fixed_at_source
        return caught / self.injected if self.injected else 1.0

    @property
    def precision(self) -> float:
        flagged = self.detected + self.extra
        return self.detected / flagged if flagged else 1.0

    @property
    def status(self) -> str:
        if not self.has_rule:
            return "NO RULE"
        return "OK" if not self.missed else "MISSED"


def export_date(export_id: str) -> str:
    """'NMS-EXPORT-20260907' -> '20260907'."""
    return export_id.rsplit("-", 1)[-1]


def alarm_files(defect_type: str, alarm_id: str) -> set[str]:
    """Export dates (YYYYMMDD) of the file(s) an alarm defect was delivered in.
    Alarm ids embed the raise date (ALM + YYYYMMDD + seq); re-exports also
    appear in the next day's file."""
    day = alarm_id[3:11]
    days = {day}
    if defect_type == "alarm_reexported":
        nxt = date(int(day[:4]), int(day[4:6]), int(day[6:])) + timedelta(days=1)
        days.add(nxt.strftime("%Y%m%d"))
    return days


def compare(
    manifest: dict[str, dict],
    detected: dict[str, set[str]],
    rejected_exports: set[str] | None = None,
    fixed_at_source: dict[str, set[str]] | None = None,
) -> list[DefectResult]:
    rejected_days = {export_date(e) for e in (rejected_exports or set())}
    fixed_at_source = fixed_at_source or {}
    results = []
    for defect_type, spec in sorted(manifest.items()):
        injected = set(spec["ids"])
        found = detected.get(defect_type)
        r = DefectResult(defect_type, injected=len(injected), has_rule=found is not None)
        found = found or set()
        r.detected = len(injected & found)
        r.extra = len(found - injected)
        for record_id in sorted(injected - found):
            if (
                defect_type.startswith("alarm_")
                and defect_type not in FILE_LEVEL_DEFECTS
                and alarm_files(defect_type, record_id) & rejected_days
            ):
                r.quarantined += 1
            elif record_id in fixed_at_source.get(defect_type, set()):
                r.fixed_at_source += 1
            else:
                r.missed.append(record_id)
        results.append(r)
    return results


def overall_recall(results: list[DefectResult]) -> float:
    injected = sum(r.injected for r in results)
    caught = sum(r.detected + r.quarantined + r.fixed_at_source for r in results)
    return caught / injected if injected else 1.0


HEADER = ["defect", "injected", "detected", "quarantined", "fixed@src", "missed", "extra", "recall"]


def render(results: list[DefectResult], markdown: bool = False) -> str:
    head = HEADER
    rows = [
        [
            r.defect_type,
            r.injected,
            r.detected,
            r.quarantined,
            r.fixed_at_source,
            len(r.missed),
            r.extra,
            f"{r.recall:.0%}" if r.has_rule else "no rule",
        ]
        for r in results
    ]
    total_injected = sum(r.injected for r in results)
    rows.append(
        [
            "TOTAL",
            total_injected,
            sum(r.detected for r in results),
            sum(r.quarantined for r in results),
            sum(r.fixed_at_source for r in results),
            sum(len(r.missed) for r in results),
            sum(r.extra for r in results),
            f"{overall_recall(results):.0%}",
        ]
    )
    if markdown:
        lines = ["| " + " | ".join(head) + " |", "|---|" + "---:|" * (len(head) - 1)]
        lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
        return "\n".join(lines)
    fmt = "{:30} {:>8} {:>8} {:>11} {:>9} {:>6} {:>6} {:>7}"
    return "\n".join(fmt.format(*(str(c) for c in row)) for row in [head, *rows])
