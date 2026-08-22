"""Shared IO/date helpers used by connectors and pipeline modules.

Not one of the modules enumerated in the original repo-structure sketch in
docs/technical-spec.md §4 — added during implementation to avoid five
connectors re-deriving the same JSON/date-path logic. See CHANGELOG.md.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import datetime, timezone

from pipeline.schema import NormalizedItem


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def iso_week_str(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    iso_year, iso_week, _ = dt.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def write_raw_items(source: str, items: Iterable[NormalizedItem], date: str | None = None) -> str:
    date = date or today_str()
    directory = os.path.join("data", "raw", source)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{date}.json")
    write_json(path, [item.to_dict() for item in items])
    return path


def read_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, data) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
