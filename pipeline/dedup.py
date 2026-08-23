"""Deduplication — see docs/technical-spec.md §9.

Reads the week's raw connector output, assigns cluster_id via exact-URL and
title-similarity grouping, and writes data/interim/<iso-week>.json for
pipeline.score to pick up next. data/interim/ is an implementation addition
beyond the original repo-structure sketch (§4) — kept as a debuggable,
inspectable file between each pipeline stage rather than an in-memory
hand-off, matching the "simple, file-based state" preference in §2.
"""

from __future__ import annotations

import argparse
import difflib
import glob
import os
import re
import sys
from datetime import datetime, timezone

from pipeline.io_utils import iso_week_str, read_json, write_json

TITLE_SIM_THRESHOLD = 0.85
JACCARD_THRESHOLD = 0.7
_EXCERPT_RANK = {"ok": 2, "partial": 1, "none": 0}


def _normalize_title(title: str) -> str:
    cleaned = re.sub(r"[^\w\s]", "", (title or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _token_set(title: str) -> set:
    return set(_normalize_title(title).split())


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _titles_match(a: str, b: str) -> bool:
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return False
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    if ratio > TITLE_SIM_THRESHOLD:
        return True
    return _jaccard(_token_set(a), _token_set(b)) > JACCARD_THRESHOLD


def load_week_raw_items(iso_week: str | None = None) -> list[dict]:
    iso_week = iso_week or iso_week_str()
    year, week = (int(p) for p in iso_week.replace("W", "").split("-"))

    items: list[dict] = []
    for path in sorted(glob.glob(os.path.join("data", "raw", "*", "*.json"))):
        date_str = os.path.basename(path)[: -len(".json")]
        try:
            file_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        file_iso_year, file_iso_week, _ = file_date.isocalendar()
        if (file_iso_year, file_iso_week) != (year, week):
            continue
        items.extend(read_json(path))

    return items


def cluster_items(items: list[dict]) -> list[dict]:
    """Assign cluster_id, cluster_sources, and cluster_excerpt to each item."""
    items = [dict(it) for it in items]
    if not items:
        return items

    valid_items = []
    for item in items:
        try:
            _ = item["id"], item["title"], item["source"]
        except KeyError as exc:
            print(f"[dedup] skipping malformed item (missing {exc}): {item}", file=sys.stderr)
            continue
        valid_items.append(item)
    items = valid_items
    if not items:
        return items

    ids = []
    id_to_title: dict[str, str] = {}
    for item in items:
        if item["id"] not in id_to_title:
            ids.append(item["id"])
            id_to_title[item["id"]] = item["title"]

    parent = {uid: uid for uid in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if _titles_match(id_to_title[ids[i]], id_to_title[ids[j]]):
                union(ids[i], ids[j])

    for item in items:
        item["cluster_id"] = find(item["id"])

    cluster_sources: dict[str, set] = {}
    best_excerpt: dict[str, tuple] = {}
    for item in items:
        cid = item["cluster_id"]
        cluster_sources.setdefault(cid, set()).add(item["source"])
        rank = _EXCERPT_RANK.get(item.get("excerpt_status", "none"), 0)
        current = best_excerpt.get(cid)
        if current is None or rank > current[0]:
            best_excerpt[cid] = (rank, item.get("excerpt", ""), item.get("excerpt_status", "none"))

    for item in items:
        cid = item["cluster_id"]
        item["cluster_sources"] = sorted(cluster_sources[cid])
        _, excerpt, excerpt_status = best_excerpt[cid]
        item["cluster_excerpt"] = excerpt
        item["cluster_excerpt_status"] = excerpt_status

    return items


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iso-week", default=None)
    args = parser.parse_args()

    iso_week = args.iso_week or iso_week_str()
    raw_items = load_week_raw_items(iso_week)
    clustered = cluster_items(raw_items)
    out_path = os.path.join("data", "interim", f"{iso_week}.json")
    write_json(out_path, clustered)
    n_clusters = len({it["cluster_id"] for it in clustered})
    print(f"[dedup] {len(raw_items)} raw items -> {n_clusters} clusters -> {out_path}")


if __name__ == "__main__":
    main()
