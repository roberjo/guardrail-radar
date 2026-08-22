"""Hacker News connector — see docs/technical-spec.md §7.1.

No auth required. Query terms come from config/keywords.yml's core_terms,
run one search per term and merged, per §7.1.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone

import requests
import yaml

from pipeline.excerpt import capture_excerpt, hn_comment_fallback
from pipeline.io_utils import write_raw_items
from pipeline.schema import NormalizedItem

SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
REQUEST_TIMEOUT = 10
QUERY_SLEEP_SECONDS = 1.0


def _load_core_terms(path: str = "config/keywords.yml") -> list[str]:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg.get("core_terms", [])


def _search(term: str, session: requests.Session) -> list[dict]:
    resp = session.get(
        SEARCH_URL,
        params={"query": term, "tags": "story"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("hits", [])


def fetch_items(terms: list[str] | None = None) -> list[NormalizedItem]:
    terms = terms if terms is not None else _load_core_terms()
    now = datetime.now(timezone.utc).isoformat()
    seen_object_ids: set[str] = set()
    items: list[NormalizedItem] = []

    with requests.Session() as session:
        for i, term in enumerate(terms):
            if i > 0:
                time.sleep(QUERY_SLEEP_SECONDS)
            try:
                hits = _search(term, session)
            except requests.RequestException as exc:
                print(f"[hn] query {term!r} failed: {exc}", file=sys.stderr)
                continue

            for hit in hits:
                object_id = hit.get("objectID")
                if not object_id or object_id in seen_object_ids:
                    continue
                seen_object_ids.add(object_id)

                url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
                fallback = (hit.get("story_text") or "").strip()
                excerpt, status = capture_excerpt(url, fallback_text=fallback, session=session)
                if status == "none":
                    comment_text = hn_comment_fallback(object_id, session=session)
                    if comment_text:
                        excerpt, status = comment_text[:1000], "partial"

                posted_at = hit.get("created_at") or now
                items.append(
                    NormalizedItem(
                        source="hn",
                        title=hit.get("title") or "(untitled)",
                        url=url,
                        raw_score=hit.get("points") or 0,
                        comment_count=hit.get("num_comments") or 0,
                        posted_at=posted_at,
                        fetched_at=now,
                        excerpt=excerpt,
                        excerpt_status=status,
                        source_meta={"object_id": object_id, "author": hit.get("author")},
                    )
                )

    return items


def main() -> None:
    items = fetch_items()
    path = write_raw_items("hn", items)
    print(f"[hn] wrote {len(items)} items to {path}")


if __name__ == "__main__":
    main()
