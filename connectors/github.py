"""GitHub connector — see docs/technical-spec.md §7.3.

Uses GH_SEARCH_TOKEN if set (5000 req/hr) for production runs; falls back to
unauthenticated (much lower limits) for local/dev use so this is runnable
without a token, per docs/technical-spec.md §16.

raw_score is log-scaled total stargazers_count, not true 7-day star
velocity — GitHub's stargazers endpoint now 404s for any repo the token
holder doesn't own/collaborate on, confirmed live against torvalds/linux
and octocat/Hello-World with a fully-scoped token (both 404; a repo the
token owner actually owns succeeds). This isn't a scope or auth problem —
GitHub has restricted third-party stargazer-timestamp enumeration
entirely, so per-repo velocity is no longer obtainable through this API
for the repos this connector actually searches. See CHANGELOG.md.
"""

from __future__ import annotations

import base64
import math
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
STAR_SCALE = 100


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


def _star_score(stargazers_count: int) -> int:
    """Log-scale total stars into roughly the same magnitude as other
    sources' point-based raw_score (HN points, Reddit ups — typically
    single-to-quadruple digits). A repo with 250k stars would otherwise
    swamp the shared velocity formula in pipeline/score.py against every
    other source, on nothing more than a routine push. Monotonic (more
    stars still always ranks higher) but compressed:
      0 stars -> 0, 100 -> 461, 1,000 -> 690, 100,000 -> 1,151
    """
    return int(math.log1p(max(stargazers_count, 0)) * STAR_SCALE)


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

                total_stars = repo.get("stargazers_count") or 0
                fallback = _readme_excerpt(full_name, repo.get("description", ""), headers, session)
                excerpt, status = capture_excerpt(url, fallback_text=fallback, session=session)

                items.append(
                    NormalizedItem(
                        source="github",
                        title=full_name,
                        url=url,
                        raw_score=_star_score(total_stars),
                        comment_count=0,
                        posted_at=repo.get("pushed_at") or repo.get("created_at") or now,
                        fetched_at=now,
                        excerpt=excerpt,
                        excerpt_status=status,
                        source_meta={
                            "open_issues_count": repo.get("open_issues_count"),
                            "total_stars": total_stars,
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
