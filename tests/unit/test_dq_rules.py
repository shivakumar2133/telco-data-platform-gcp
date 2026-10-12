"""The rule catalogue covers every defect type the data generator can inject."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULES = (ROOT / "transform" / "macros" / "dq_rules.sql").read_text()


def injected_defect_types() -> set[str]:
    src = "".join(p.read_text() for p in (ROOT / "data_generator").rglob("*.py"))
    return set(re.findall(r'\.add\(\s*"([a-z_]+)"', src))  # DefectLog.add("<type>", ...)


def rule_defect_types() -> set[str]:
    return set(re.findall(r"'defect_type':\s*'([a-z_]+)'", RULES))


def test_every_injected_defect_type_has_a_rule():
    injected = injected_defect_types()
    assert len(injected) == 20
    assert injected <= rule_defect_types(), injected - rule_defect_types()


def test_rule_ids_are_unique():
    ids = re.findall(r"\{'id':\s*'([a-z_]+)'", RULES)
    assert len(ids) == len(set(ids)) == 24
