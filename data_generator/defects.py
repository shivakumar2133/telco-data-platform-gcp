"""Deliberate data defects, recorded in a manifest.

Why: in Phase 7 the pipeline's quality checks and reconciliation must find
exactly what we injected here. "Expected defects vs detected defects" is the
strongest proof a DQ framework works (and a great interview story).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class DefectLog:
    def __init__(self) -> None:
        self._items: dict[str, dict] = {}

    def add(self, name: str, system: str, description: str, ids, **extra) -> None:
        ids = [str(i) for i in ids]
        entry = self._items.setdefault(
            name, {"system": system, "description": description, "count": 0, "ids": []}
        )
        entry["count"] += len(ids)
        entry["ids"].extend(ids)
        for key, value in extra.items():
            if isinstance(value, int | float) and isinstance(entry.get(key), int | float):
                entry[key] = round(entry[key] + value, 2)
            else:
                entry[key] = value

    def count(self, name: str) -> int:
        return self._items.get(name, {}).get("count", 0)

    def ids(self, name: str) -> list[str]:
        return list(self._items.get(name, {}).get("ids", []))

    def to_dict(self) -> dict:
        return {k: dict(v) for k, v in sorted(self._items.items())}

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str))


def pick(rng: np.random.Generator, population: int, rate: float, minimum: int = 1) -> np.ndarray:
    """Return sorted, unique row positions: rate * population (at least `minimum`)."""
    if population <= 0:
        return np.array([], dtype=int)
    k = min(population, max(minimum, int(round(population * rate))))
    return np.sort(rng.choice(population, size=k, replace=False))
