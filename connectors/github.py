"""GitHub connector — see docs/technical-spec.md §7.3.

Uses GH_SEARCH_TOKEN if set (5000 req/hr) for production runs; falls back to
unauthenticated (much lower limits) for local/dev use so this is runnable
without a token, per docs/technical-spec.md §16.
"""

from __future__ import annotations

import base64
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
import yaml

from pipeline.excerpt import capture_excerpt
from pipeline.io_utils import write_raw_items
from pipeline.schema import NormalizedItem

API_ROOT = "https://api.github.com"
REQUEST_TIMEOUT = 10
MAX_REPOS_PER_TOPIC = 10


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GH_SEARCH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        print("[github] GH_SEARCH_TOKEN not set — running unauthenticated, low rate limits", file=sys.stderr)
    return headers


def _load_config(path: str = "config/sources.yml") -> dict:
    with open(path, encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("github", {})


def _search_repos(topic: str, since: datetime, headers: dict, session: requests.Session) -> list[dict]:
    query = f"topic:{topic} pushed:>={since.date().isoformat()}"
    resp = session.get(
        f"{API_ROOT}/search/repositories",
        params={"q": query, "sort": "updated", "order": "desc", "per_page": str(MAX_REPOS_PER_TOPIC)},
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


def _stars_last_7d(full_name: str, headers: dict, session: requests.Session) -> int:
    star_headers = dict(headers)
    star_headers["Accept"] = "application/vnd.github.star+json"
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    count = 0
    try:
        resp = session.get(
            f"{API_ROOT}/repos/{full_name}/stargazers",
            params={"per_page": 100},
            headers=star_headers,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        for entry in resp.json():
            starred_at = entry.get("starred_at")
            if not starred_at:
                continue
            parsed = datetime.fromisoformat(starred_at.replace("Z", "+00:00"))
            if parsed >= cutoff:
                count += 1
    except requests.RequestException as exc:
        print(f"[github] stargazers fetch failed for {full_name}: {exc}", file=sys.stderr)
    return count


def _readme_first_paragraph(content: str) -> str:
    """First real body paragraph — not a heading, image, or badge.

    `.lstrip("#")` used to strip a leading "# " off a heading and return
    the bare title text (e.g. "Project Title") as if it were the first
    paragraph — every README starts with a heading, so this was returning
    the title, not any actual description, on effectively every repo.
    Found by a test that used a realistic "# Title\\n\\nBody" README shape.
    """
    for para in content.split("\n\n"):
        cleaned = para.strip()
        if not cleaned or cleaned.startswith(("#", "![", "<", "[![")):
            continue
        return cleaned
    return ""


def _readme_excerpt(full_name: str, description: str, headers: dict, session: requests.Session) -> str:
    content = ""
    try:
        resp = session.get(f"{API_ROOT}/repos/{full_name}/readme", headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json().get("content", "")
        content = base64.b64decode(raw).decode("utf-8", errors="replace")
    except requests.RequestException:
        pass

    parts = [p for p in (description or "", _readme_first_paragraph(content)) if p]
    return " — ".join(parts)[:1000]


def fetch_items() -> list[NormalizedItem]:
    cfg = _load_config()
    topics = cfg.get("topics", [])
    window_days = cfg.get("window_days", 30)
    headers = _headers()
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    now = datetime.now(timezone.utc).isoformat()

    seen_full_names: set[str] = set()
    items: list[NormalizedItem] = []

    has_token = "Authorization" in headers
    if not has_token:
        # The star+json media type 401s even for public repos without auth —
        # confirmed by a live test run. Skip it entirely rather than burning
        # unauthenticated rate-limit budget on calls known to fail.
        print(
            "[github] no GH_SEARCH_TOKEN: skipping stars_last_7d lookups "
            "(GitHub requires auth for starred_at timestamps even on public "
            "repos) — raw_score will be 0 for this run",
            file=sys.stderr,
        )

    with requests.Session() as session:
        for i, topic in enumerate(topics):
            if i > 0:
                time.sleep(2)
            try:
                repos = _search_repos(topic, since, headers, session)
            except requests.RequestException as exc:
                print(f"[github] search for topic {topic!r} failed: {exc}", file=sys.stderr)
                continue

            for repo in repos:
                full_name = repo.get("full_name")
                if not full_name or full_name in seen_full_names:
                    continue
                seen_full_names.add(full_name)

                url = repo.get("html_url")
                if not url:
                    # Not expected from a real GitHub API response, but
                    # NormalizedItem requires a url — skip rather than crash
                    # on a str(None)/AttributeError inside canonicalize_url.
                    print(f"[github] skipping {full_name!r} with no html_url", file=sys.stderr)
                    continue

                stars_7d = _stars_last_7d(full_name, headers, session) if has_token else 0
                fallback = _readme_excerpt(full_name, repo.get("description", ""), headers, session)
                excerpt, status = capture_excerpt(url, fallback_text=fallback, session=session)

                items.append(
                    NormalizedItem(
                        source="github",
                        title=full_name,
                        url=url,
                        raw_score=stars_7d,
                        comment_count=0,
                        posted_at=repo.get("pushed_at") or repo.get("created_at") or now,
                        fetched_at=now,
                        excerpt=excerpt,
                        excerpt_status=status,
                        source_meta={
                            "open_issues_count": repo.get("open_issues_count"),
                            "total_stars": repo.get("stargazers_count"),
                            "topic": topic,
                        },
                    )
                )

    return items


def main() -> None:
    items = fetch_items()
    path = write_raw_items("github", items)
    print(f"[github] wrote {len(items)} items to {path}")


if __name__ == "__main__":
    main()
