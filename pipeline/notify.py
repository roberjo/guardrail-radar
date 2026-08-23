"""pipeline.notify — see docs/technical-spec.md §15.2.

Opens (or updates) a GitHub Issue to tell the maintainer a review packet is
ready to draft against. Never sends anything to subscribers — see
docs/technical-spec.md §1, §20.

Replaced the original Gmail SMTP mechanism: an app password is real friction
for a zero-budget solo project (2FA setup, a Google-account-specific manual
step) for a notification GitHub can already deliver for free. Opening an
issue needs no new credential at all — the GITHUB_TOKEN every Actions run
already gets can create issues once the workflow grants `issues: write` —
and GitHub's own notification system (email/web/mobile) delivers the same
ping to anyone watching the repo, which as the repo owner you already are
by default. See CHANGELOG.md.
"""

from __future__ import annotations

import argparse
import os

import requests

from pipeline.io_utils import iso_week_str, read_json

API_ROOT = "https://api.github.com"
REQUEST_TIMEOUT = 10


def _ranked_count(iso_week: str) -> int:
    path = os.path.join("data", "ranked", f"{iso_week}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} does not exist — pipeline.filter has not produced a ranked file for "
            f"{iso_week} yet; refusing to open a review-packet-ready notification"
        )
    return len(read_json(path))


def _headers() -> dict:
    token = os.environ["GITHUB_TOKEN"]
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _find_open_issue(repo: str, title: str, session: requests.Session) -> dict | None:
    # Idempotency matters here the same way it did for the site archive
    # (see CHANGELOG.md) — a re-run of this workflow for a week that
    # already has a ready notification should never open a second one.
    resp = session.get(
        f"{API_ROOT}/search/issues",
        params={"q": f'repo:{repo} type:issue state:open in:title "{title}"'},
        headers=_headers(),
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    for item in resp.json().get("items", []):
        if item.get("title") == title:
            return item
    return None


def open_review_packet_issue(iso_week: str, item_count: int, session: requests.Session | None = None) -> dict:
    repo = os.environ["GITHUB_REPOSITORY"]
    title = f"Review packet ready: {iso_week}"
    body = (
        f"{item_count} candidates ranked for {iso_week}.\n\n"
        f"Review packet: `digest/review/{iso_week}.md`\n\n"
        "Next: run the `draft-digest` skill, then `verify-and-ship-digest`."
    )

    owns_session = session is None
    session = session or requests.Session()
    try:
        existing = _find_open_issue(repo, title, session)
        if existing is not None:
            return existing

        resp = session.post(
            f"{API_ROOT}/repos/{repo}/issues",
            json={"title": title, "body": body, "labels": ["digest"]},
            headers=_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns_session:
            session.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["review-packet-ready"], required=True)
    parser.add_argument("--iso-week", default=None)
    args = parser.parse_args()

    iso_week = args.iso_week or iso_week_str()

    if args.kind == "review-packet-ready":
        issue = open_review_packet_issue(iso_week, _ranked_count(iso_week))
        print(f"[notify] issue ready for {iso_week}: {issue.get('html_url', issue.get('title'))}")


if __name__ == "__main__":
    main()
