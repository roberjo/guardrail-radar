"""Reddit connector — see docs/technical-spec.md §7.2.

Requires REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET (a free "script" app). Cannot
be live-tested without real credentials — verified against a mocked OAuth
+ listing response in tests/test_reddit.py instead.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlsplit

import requests
import yaml

from pipeline.excerpt import capture_excerpt
from pipeline.io_utils import write_raw_items
from pipeline.schema import NormalizedItem

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_ROOT = "https://oauth.reddit.com"
REQUEST_TIMEOUT = 10
USER_AGENT = "guardrail-radar-bot/1.0 (curated newsletter; contact via project repo)"
MIN_REQUEST_INTERVAL = 1.1  # keeps us comfortably under Reddit's 60 req/min OAuth limit
REMOVED_PLACEHOLDERS = {"[removed]", "[deleted]"}


def _load_config(path: str = "config/sources.yml") -> tuple[list[str], list[str]]:
    with open(path, encoding="utf-8") as f:
        cfg = (yaml.safe_load(f) or {}).get("reddit", {})
    return cfg.get("subreddits", []), cfg.get("listings", ["new"])


def _load_keywords(path: str = "config/keywords.yml") -> list[str]:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg.get("core_terms", []) + cfg.get("context_terms", [])


def get_token(session: requests.Session) -> str:
    client_id = os.environ["REDDIT_CLIENT_ID"]
    client_secret = os.environ["REDDIT_CLIENT_SECRET"]
    resp = session.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _matches(post: dict, keywords: list[str]) -> bool:
    haystack = f"{post.get('title', '')} {post.get('selftext', '')}".lower()
    return any(term.lower() in haystack for term in keywords)


def _parse_listing(listing: str) -> tuple[str, dict]:
    """'top?t=week' -> ('top', {'t': 'week'}); 'new' -> ('new', {})."""
    parts = urlsplit(listing)
    path = parts.path or listing
    params = dict(parse_qsl(parts.query))
    return path, params


def _comment_fallback(
    subreddit: str, post_id: str, headers: dict, session: requests.Session
) -> str:
    """Top comment body for a link post with no retrievable primary excerpt (§6)."""
    try:
        resp = session.get(
            f"{API_ROOT}/r/{subreddit}/comments/{post_id}",
            headers=headers,
            params={"limit": 1, "raw_json": 1},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return ""

    try:
        comments_listing = data[1]
    except (IndexError, TypeError, KeyError):
        return ""

    for child in comments_listing.get("data", {}).get("children", []):
        if child.get("kind") == "t1":
            return (child.get("data", {}).get("body") or "").strip()
    return ""


def fetch_items() -> list[NormalizedItem]:
    subreddits, listings = _load_config()
    keywords = _load_keywords()

    now = datetime.now(timezone.utc).isoformat()
    seen_ids: set[str] = set()
    items: list[NormalizedItem] = []
    last_request = 0.0

    with requests.Session() as session:
        token = get_token(session)
        headers = {"Authorization": f"bearer {token}", "User-Agent": USER_AGENT}

        for subreddit in subreddits:
            for listing in listings:
                elapsed = time.monotonic() - last_request
                if elapsed < MIN_REQUEST_INTERVAL:
                    time.sleep(MIN_REQUEST_INTERVAL - elapsed)

                listing_path, params = _parse_listing(listing)
                params["raw_json"] = 1
                url = f"{API_ROOT}/r/{subreddit}/{listing_path}"

                try:
                    resp = session.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
                    last_request = time.monotonic()
                    resp.raise_for_status()
                    listing_data = resp.json()
                except (requests.RequestException, ValueError) as exc:
                    print(f"[reddit] r/{subreddit}/{listing} failed: {exc}", file=sys.stderr)
                    continue

                for child in listing_data.get("data", {}).get("children", []):
                    post = child.get("data", {})
                    post_id = post.get("id")
                    if not post_id or post_id in seen_ids:
                        continue
                    if not _matches(post, keywords):
                        continue
                    seen_ids.add(post_id)

                    if post.get("is_self"):
                        post_url = f"https://reddit.com{post.get('permalink', '')}"
                    else:
                        post_url = post.get("url") or f"https://reddit.com{post.get('permalink', '')}"

                    fallback = (post.get("selftext") or "").strip()
                    if fallback in REMOVED_PLACEHOLDERS:
                        fallback = ""
                    excerpt, status = capture_excerpt(post_url, fallback_text=fallback, session=session)
                    if status == "none" and not post.get("is_self"):
                        comment_text = _comment_fallback(subreddit, post_id, headers, session)
                        if comment_text:
                            title = post.get("title") or ""
                            combined = f"{title} {comment_text}".strip()
                            excerpt, status = combined[:1000], "partial"

                    items.append(
                        NormalizedItem(
                            source="reddit",
                            title=post.get("title") or "(untitled)",
                            url=post_url,
                            raw_score=post.get("ups") or 0,
                            comment_count=post.get("num_comments") or 0,
                            posted_at=datetime.fromtimestamp(
                                post.get("created_utc", 0), tz=timezone.utc
                            ).isoformat(),
                            fetched_at=now,
                            excerpt=excerpt,
                            excerpt_status=status,
                            source_meta={"subreddit": subreddit, "post_id": post_id},
                        )
                    )

    return items


def main() -> None:
    items = fetch_items()
    path = write_raw_items("reddit", items)
    print(f"[reddit] wrote {len(items)} items to {path}")


if __name__ == "__main__":
    main()
