"""lobste.rs connector — see docs/technical-spec.md §8.1.

Public JSON feeds, no auth.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import requests
import yaml

from pipeline.excerpt import capture_excerpt
from pipeline.io_utils import write_raw_items
from pipeline.schema import NormalizedItem

FEEDS = ["https://lobste.rs/newest.json", "https://lobste.rs/hottest.json"]
REQUEST_TIMEOUT = 10


def _load_tags(path: str = "config/sources.yml") -> list[str]:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg.get("lobsters", {}).get("tags", [])


def _load_keywords(path: str = "config/keywords.yml") -> list[str]:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg.get("core_terms", []) + cfg.get("context_terms", [])


def _matches(story: dict, tags: list[str], keywords: list[str]) -> bool:
    story_tags = {t.lower() for t in story.get("tags", [])}
    if story_tags & {t.lower() for t in tags}:
        return True
    haystack = f"{story.get('title', '')} {story.get('description', '')}".lower()
    return any(term.lower() in haystack for term in keywords)


def fetch_items() -> list[NormalizedItem]:
    tags = _load_tags()
    keywords = _load_keywords()
    now = datetime.now(timezone.utc).isoformat()
    seen_short_ids: set[str] = set()
    items: list[NormalizedItem] = []

    with requests.Session() as session:
        for feed_url in FEEDS:
            try:
                resp = session.get(feed_url, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                stories = resp.json()
            except (requests.RequestException, ValueError) as exc:
                print(f"[lobsters] {feed_url} failed: {exc}", file=sys.stderr)
                continue

            for story in stories:
                short_id = story.get("short_id")
                if not short_id or short_id in seen_short_ids:
                    continue
                if not _matches(story, tags, keywords):
                    continue
                seen_short_ids.add(short_id)

                url = story.get("url") or story.get("comments_url")
                if not url:
                    continue
                fallback = (story.get("description") or "").strip()
                excerpt, status = capture_excerpt(url, fallback_text=fallback, session=session)

                items.append(
                    NormalizedItem(
                        source="lobsters",
                        title=story.get("title") or "(untitled)",
                        url=url,
                        raw_score=story.get("score") or 0,
                        comment_count=story.get("comment_count") or 0,
                        posted_at=story.get("created_at") or now,
                        fetched_at=now,
                        excerpt=excerpt,
                        excerpt_status=status,
                        source_meta={"short_id": short_id, "tags": story.get("tags", [])},
                    )
                )

    return items


def main() -> None:
    items = fetch_items()
    path = write_raw_items("lobsters", items)
    print(f"[lobsters] wrote {len(items)} items to {path}")


if __name__ == "__main__":
    main()
