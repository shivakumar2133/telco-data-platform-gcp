"""Generator settings. One seed + one scale factor = fully reproducible data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class GenConfig:
    seed: int = 42
    scale: float = 1.0  # 1.0 = 5,000 customers, ~900k CDRs. Use 0.1 for a quick run.
    history_start: date = date(2026, 7, 1)  # first billed month
    history_end: date = date(2026, 9, 30)  # last billed month
    cdr_start: date = date(2026, 9, 1)  # CDR + alarm files cover this window
    cdr_days: int = 30
    as_of: date = date(2026, 10, 5)  # "today" inside the synthetic world

    @property
    def n_customers(self) -> int:
        return max(50, int(5000 * self.scale))

    @property
    def n_sites(self) -> int:
        return max(10, int(300 * self.scale))
