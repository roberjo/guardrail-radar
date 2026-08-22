"""Scoring — see docs/technical-spec.md §10.

Reads data/interim/<iso-week>.json (written by pipeline.dedup), adds
velocity_score/item_score/cluster_score in place, and overwrites the same
file — pipeline.filter reads it next.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from dateutil import parser as date_parser

from pipeline.io_utils import iso_week_str, read_json, write_json

CROSS_SOURCE_BONUS = 0.25


def _hours_since(posted_at: str, now: datetime) -> float:
    posted = date_parser.isoparse(posted_at)
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    delta = now - posted
    return max(1.0, delta.total_seconds() / 3600.0)


def compute_item_score(item: dict, now: datetime) -> tuple[float, float]:
    """Return (velocity_score, item_score) per §10."""
    hours = _hours_since(item["posted_at"], now)
    raw_score = max(item.get("raw_score", 0), 0)
    comment_count = max(item.get("comment_count", 0), 0)
    velocity_score = raw_score / hours
    discussion_ratio = comment_count / max(1, raw_score)
    item_score = velocity_score * (1 + min(discussion_ratio, 1.0))
    return velocity_score, item_score


def score_items(items: list[dict], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    items = [dict(it) for it in items]

    valid_items = []
    for item in items:
        try:
            velocity_score, item_score = compute_item_score(item, now)
        except (KeyError, ValueError, TypeError) as exc:
            print(f"[score] skipping malformed item (id={item.get('id', '?')}): {exc}", file=sys.stderr)
            continue
        item["velocity_score"] = velocity_score
        item["item_score"] = item_score
        valid_items.append(item)
    items = valid_items
    if not items:
        return items

    clusters: dict[str, list[dict]] = {}
    for item in items:
        clusters.setdefault(item["cluster_id"], []).append(item)

    cluster_scores: dict[str, float] = {}
    for cluster_id, cluster_items_ in clusters.items():
        max_item_score = max(ci["item_score"] for ci in cluster_items_)
        distinct_sources = len({ci["source"] for ci in cluster_items_})
        cluster_scores[cluster_id] = max_item_score * (1 + CROSS_SOURCE_BONUS * (distinct_sources - 1))

    for item in items:
        item["cluster_score"] = cluster_scores[item["cluster_id"]]

    return items


def main() -> None:
    iso_week = iso_week_str()
    path = os.path.join("data", "interim", f"{iso_week}.json")
    items = read_json(path)
    scored = score_items(items)
    write_json(path, scored)
    print(f"[score] scored {len(scored)} items across {len({i['cluster_id'] for i in scored})} clusters")


if __name__ == "__main__":
    main()
