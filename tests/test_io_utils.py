"""Tests for pipeline.io_utils — see docs/technical-spec.md §18."""

import json
import os
from datetime import datetime, timezone

from pipeline.io_utils import (
    iso_week_str,
    read_json,
    today_str,
    write_json,
    write_raw_items,
)
from pipeline.schema import NormalizedItem


def test_today_str_format():
    assert today_str() == datetime.now(timezone.utc).strftime("%Y-%m-%d")


def test_iso_week_str_known_date():
    # 2026-01-01 is a Thursday, ISO week 1 of 2026.
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert iso_week_str(dt) == "2026-W01"


def test_iso_week_str_pads_single_digit_weeks():
    dt = datetime(2026, 1, 5, tzinfo=timezone.utc)
    week = iso_week_str(dt)
    assert week.split("-W")[1].isdigit()
    assert len(week.split("-W")[1]) == 2


def test_write_json_read_json_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = {"a": 1, "b": [1, 2, 3]}
    write_json("nested/dir/out.json", data)
    assert read_json("nested/dir/out.json") == data


def test_write_raw_items_creates_source_directory_and_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    item = NormalizedItem(
        source="hn",
        title="x",
        url="https://example.com/a",
        raw_score=1,
        comment_count=0,
        posted_at="2026-01-01T00:00:00Z",
        fetched_at="2026-01-01T00:00:00Z",
    )
    path = write_raw_items("hn", [item], date="2026-01-01")
    assert path == os.path.join("data", "raw", "hn", "2026-01-01.json")
    with open(path, encoding="utf-8") as f:
        written = json.load(f)
    assert written == [item.to_dict()]
