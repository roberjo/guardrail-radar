"""Beehiiv API v2 client — see .claude/skills/beehiiv-api/SKILL.md.

Read-only publication/subscriber stats, plus creating DRAFT posts only.
This module must never trigger a real subscriber-facing send: that stays a
deliberate human action in the Beehiiv dashboard (docs/weekly-runbook.md),
same as every other publish step in this pipeline (see
_assert_no_unresolved_blocked in pipeline/render.py and the two-layer
content model in docs/editorial-guidelines.md). create_draft_post always
passes "status": "draft" explicitly — never rely on Beehiiv's own default
for something this consequential, and never add a function here that can
set a post to "confirmed" or call Beehiiv's separate Send API.

Endpoint shapes below are transcribed from developers.beehiiv.com — see the
skill's references/api-reference.md for the exact pages and confirmed
fields. Nothing here is guessed.
"""

from __future__ import annotations

import os
import time

import requests

API_BASE = "https://api.beehiiv.com/v2"

# Not a secret — publication ids are visible in the publication's own
# dashboard URL and in every API response. Read from BEEHIIV_PUB_API_KEY
# (the maintainer's own env var name for it — see .env.example) so it's
# not a second hardcoded value to keep in sync by hand; falls back to the
# real id given directly by the maintainer on 2026-08-24 (see
# docs/project-plan.md §11 and the beehiiv-account project memory) so this
# still works in contexts (e.g. CI) that haven't set the env var.
PUBLICATION_ID = os.environ.get("BEEHIIV_PUB_API_KEY", "pub_ce3a249a-ebd9-4d23-8c43-1ca597987269")

REQUEST_TIMEOUT = 15
POST_CREATE_POLL_ATTEMPTS = 6
POST_CREATE_POLL_DELAY_SECONDS = 2.0


class BeehiivError(RuntimeError):
    pass


def _headers() -> dict:
    api_key = os.environ.get("BEEHIIV_API_KEY")
    if not api_key:
        raise BeehiivError("BEEHIIV_API_KEY is not set — see .env.example")
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def get_publication(expand_stats: bool = True) -> dict:
    """GET /v2/publications/{id} — name, organization, and (when
    expand_stats) subscriber/engagement stats: active_subscriptions,
    active_premium_subscriptions, active_free_subscriptions,
    average_open_rate, average_click_rate, total_sent, total_unique_opened,
    total_clicked. `stats` values are only present when requested.
    """
    params = {"expand[]": "stats"} if expand_stats else {}
    resp = requests.get(
        f"{API_BASE}/publications/{PUBLICATION_ID}",
        headers=_headers(), params=params, timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["data"]


def list_posts(limit: int = 10, status: str = "all") -> list[dict]:
    """GET /v2/publications/{id}/posts — most recently created first.
    `status` is one of draft/confirmed/archived/all.
    """
    params: dict[str, str | int] = {
        "limit": limit, "status": status, "order_by": "created", "direction": "desc",
    }
    resp = requests.get(
        f"{API_BASE}/publications/{PUBLICATION_ID}/posts",
        headers=_headers(), params=params, timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["data"]


def get_post(post_id: str) -> dict:
    """GET /v2/publications/{id}/posts/{post_id}.

    Post creation is asynchronous on Beehiiv's side — a post fetched too
    soon after creation can come back 202 (still processing) rather than
    200. Returns {"status": "_pending"} in that case, a sentinel
    create_draft_post polls on; never a real Beehiiv status value, so it
    can't be confused with one. A confirmed-failed creation (404 +
    POST_CREATION_FAILED) raises instead of silently returning nothing.
    """
    resp = requests.get(
        f"{API_BASE}/publications/{PUBLICATION_ID}/posts/{post_id}",
        headers=_headers(), timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == 202:
        return {"status": "_pending"}
    if resp.status_code == 404:
        body = resp.json() if resp.content else {}
        if body.get("error") == "POST_CREATION_FAILED":
            raise BeehiivError(f"Beehiiv failed to create post {post_id!r} — try again.")
    resp.raise_for_status()
    return resp.json()["data"]


def create_draft_post(title: str, body_content: str, subtitle: str = "") -> dict:
    """POST /v2/publications/{id}/posts — always created as a DRAFT.

    Polls get_post afterward (creation is asynchronous — see its
    docstring) until it's no longer pending, then hard-fails if the final
    status isn't "draft". This is deliberately paranoid: a bug here that
    let a post go live unnoticed would be a real, irreversible
    subscriber-facing mistake, not a cosmetic one.
    """
    payload: dict = {"title": title, "body_content": body_content, "status": "draft"}
    if subtitle:
        payload["subtitle"] = subtitle

    resp = requests.post(
        f"{API_BASE}/publications/{PUBLICATION_ID}/posts",
        headers=_headers(), json=payload, timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    post_id = resp.json()["data"]["id"]

    post: dict = {"status": "_pending"}
    for _ in range(POST_CREATE_POLL_ATTEMPTS):
        post = get_post(post_id)
        if post.get("status") != "_pending":
            break
        time.sleep(POST_CREATE_POLL_DELAY_SECONDS)

    if post.get("status") == "_pending":
        raise BeehiivError(
            f"Post {post_id!r} is still being created after {POST_CREATE_POLL_ATTEMPTS} checks — "
            "check it manually in the Beehiiv dashboard before assuming anything about it."
        )
    if post.get("status") != "draft":
        raise BeehiivError(
            f"Post {post_id!r} was created with status={post.get('status')!r}, not 'draft' — "
            "check it in the Beehiiv dashboard immediately."
        )
    return post


def push_draft(iso_week: str) -> dict:
    """Builds this week's issue as a Beehiiv draft post and creates it —
    see pipeline.render.build_beehiiv_draft_content for the content itself.
    Returns the created post record (status guaranteed "draft" or this
    raises — see create_draft_post).
    """
    from pipeline.render import build_beehiiv_draft_content

    title, body_content = build_beehiiv_draft_content(iso_week)
    return create_draft_post(title, body_content)


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["publication", "posts", "push-draft"], required=True)
    parser.add_argument("--iso-week", default=None, help="required for --action push-draft")
    args = parser.parse_args()

    if args.action == "publication":
        print(json.dumps(get_publication(), indent=2))
    elif args.action == "posts":
        print(json.dumps(list_posts(), indent=2))
    else:
        if not args.iso_week:
            parser.error("--action push-draft requires --iso-week")
        post = push_draft(args.iso_week)
        print(f"[beehiiv] created draft post {post['id']!r} — review it in the Beehiiv dashboard before sending.")
        print(json.dumps(post, indent=2))


if __name__ == "__main__":
    main()
