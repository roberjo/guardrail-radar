"""Product Hunt connector — see docs/technical-spec.md §8.2.

Requires PRODUCTHUNT_TOKEN (a free developer token). Cannot be live-tested
without real credentials — verified against a mocked GraphQL response in
tests/test_producthunt.py instead.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import requests
import yaml

from pipeline.excerpt import capture_excerpt
from pipeline.io_utils import write_raw_items
from pipeline.schema import NormalizedItem

API_URL = "https://api.producthunt.com/v2/api/graphql"
REQUEST_TIMEOUT = 10
PAGE_SIZE = 50
MAX_PAGES = 5  # hard cap so a runaway pagination loop can't outlast a CI job

QUERY = f"""
query Posts($postedAfter: DateTime!, $after: String, $topic: String) {{
  posts(postedAfter: $postedAfter, order: NEWEST, after: $after, first: {PAGE_SIZE}, topic: $topic) {{
    edges {{
      node {{
        id
        name
        tagline
        description
        url
        votesCount
        commentsCount
        createdAt
        topics(first: 10) {{ edges {{ node {{ slug }} }} }}
      }}
    }}
    pageInfo {{ hasNextPage endCursor }}
  }}
}}
"""


def _load_config(path: str = "config/sources.yml") -> dict:
    with open(path, encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("producthunt", {})


def _first_paragraph(description: str) -> str:
    """First paragraph of a PH description, per docs/technical-spec.md §8.2 —
    not the whole thing, which could crowd out the tagline or cut off
    mid-sentence once capture_excerpt truncates at 1000 chars."""
    for para in description.split("\n\n"):
        cleaned = para.strip()
        if cleaned:
            return cleaned
    return ""


def _fetch_topic_posts(
    topic: str | None,
    posted_after: str,
    headers: dict,
    session: requests.Session,
    topics_filter: set[str],
    seen_ids: set[str],
    items: list[NormalizedItem],
    now: str,
) -> None:
    after = None

    for _page in range(MAX_PAGES):
        try:
            resp = session.post(
                API_URL,
                json={
                    "query": QUERY,
                    "variables": {"postedAfter": posted_after, "after": after, "topic": topic},
                },
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            print(f"[producthunt] request failed: {exc}", file=sys.stderr)
            break

        data = payload.get("data")
        if payload.get("errors"):
            print(f"[producthunt] API error: {payload['errors']}", file=sys.stderr)
            if not data:
                break

        posts = (data or {}).get("posts", {})
        for edge in posts.get("edges", []):
            node = edge["node"]
            node_id = node.get("id")
            if node_id in seen_ids:
                continue

            node_topics = {
                t["node"]["slug"].lower() for t in node.get("topics", {}).get("edges", [])
            }
            if topics_filter and not (node_topics & topics_filter):
                continue

            url = node.get("url")
            if not url:
                print(f"[producthunt] skipping post {node_id!r} with no url", file=sys.stderr)
                continue
            seen_ids.add(node_id)

            fallback = " — ".join(
                p for p in (node.get("tagline"), _first_paragraph(node.get("description") or "")) if p
            )
            excerpt, status = capture_excerpt(url, fallback_text=fallback, session=session)

            items.append(
                NormalizedItem(
                    source="producthunt",
                    title=node.get("name") or "(untitled)",
                    url=url,
                    raw_score=node.get("votesCount") or 0,
                    comment_count=node.get("commentsCount") or 0,
                    posted_at=node.get("createdAt") or now,
                    fetched_at=now,
                    excerpt=excerpt,
                    excerpt_status=status,
                    source_meta={"ph_id": node.get("id"), "topics": sorted(node_topics)},
                )
            )

        page_info = posts.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")


def fetch_items() -> list[NormalizedItem]:
    cfg = _load_config()
    topics_cfg = list(cfg.get("topics", []))
    topics_filter = {t.lower() for t in topics_cfg}
    window_days = cfg.get("window_days", 7)
    token = os.environ["PRODUCTHUNT_TOKEN"]

    posted_after = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    now = datetime.now(timezone.utc).isoformat()

    items: list[NormalizedItem] = []
    seen_ids: set[str] = set()
    query_topics: list[str | None] = list(topics_cfg) if topics_cfg else [None]

    with requests.Session() as session:
        for topic in query_topics:
            _fetch_topic_posts(
                topic=topic,
                posted_after=posted_after,
                headers=headers,
                session=session,
                topics_filter=topics_filter,
                seen_ids=seen_ids,
                items=items,
                now=now,
            )

    return items


def main() -> None:
    items = fetch_items()
    path = write_raw_items("producthunt", items)
    print(f"[producthunt] wrote {len(items)} items to {path}")


if __name__ == "__main__":
    main()
