"""Tests for pipeline.notify — see docs/technical-spec.md §15.2, §18.

No live network calls — requests.Session is mocked. Confirms this opens a
GitHub Issue (no Gmail/SMTP involved) and never duplicates one for a week
that already has an open notification.
"""

import os
from unittest.mock import MagicMock, patch

from pipeline.notify import open_review_packet_issue


def _search_response(items: list[dict]):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"items": items}
    return resp


def _issue_response(title: str, html_url: str = "https://github.com/roberjo/guardrail-radar/issues/1"):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"title": title, "html_url": html_url}
    return resp


def test_opens_issue_with_week_title_and_item_count():
    session = MagicMock()
    session.get.return_value = _search_response([])
    session.post.return_value = _issue_response("Review packet ready: 2026-W07")

    with patch.dict(os.environ, {"GITHUB_TOKEN": "tok", "GITHUB_REPOSITORY": "roberjo/guardrail-radar"}):
        issue = open_review_packet_issue("2026-W07", 9, session=session)

    assert issue["title"] == "Review packet ready: 2026-W07"
    post_kwargs = session.post.call_args.kwargs
    assert post_kwargs["json"]["title"] == "Review packet ready: 2026-W07"
    assert "9 candidates" in post_kwargs["json"]["body"]
    assert "digest/review/2026-W07.md" in post_kwargs["json"]["body"]
    assert "draft-digest" in post_kwargs["json"]["body"]


def test_does_not_duplicate_an_existing_open_issue_for_the_same_week():
    session = MagicMock()
    session.get.return_value = _search_response(
        [{"title": "Review packet ready: 2026-W07", "html_url": "https://github.com/x/y/issues/5"}]
    )

    with patch.dict(os.environ, {"GITHUB_TOKEN": "tok", "GITHUB_REPOSITORY": "roberjo/guardrail-radar"}):
        issue = open_review_packet_issue("2026-W07", 9, session=session)

    assert issue["html_url"] == "https://github.com/x/y/issues/5"
    session.post.assert_not_called()


def test_search_result_title_must_match_exactly_not_just_contain():
    # GitHub's issue search is fuzzy full-text, not exact — a stale/similar
    # title from a different week must not be mistaken for this week's.
    session = MagicMock()
    session.get.return_value = _search_response(
        [{"title": "Review packet ready: 2026-W06", "html_url": "https://github.com/x/y/issues/4"}]
    )
    session.post.return_value = _issue_response("Review packet ready: 2026-W07")

    with patch.dict(os.environ, {"GITHUB_TOKEN": "tok", "GITHUB_REPOSITORY": "roberjo/guardrail-radar"}):
        issue = open_review_packet_issue("2026-W07", 9, session=session)

    assert issue["title"] == "Review packet ready: 2026-W07"
    session.post.assert_called_once()


def test_uses_bearer_auth_header_from_github_token():
    session = MagicMock()
    session.get.return_value = _search_response([])
    session.post.return_value = _issue_response("Review packet ready: 2026-W07")

    with patch.dict(os.environ, {"GITHUB_TOKEN": "tok_abc", "GITHUB_REPOSITORY": "roberjo/guardrail-radar"}):
        open_review_packet_issue("2026-W07", 1, session=session)

    assert session.post.call_args.kwargs["headers"]["Authorization"] == "Bearer tok_abc"
    assert session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer tok_abc"


def test_never_sends_to_an_email_recipient():
    # Regression guard against the old Gmail-based mechanism reappearing —
    # this notification is repo-internal (an Issue), never an email send.
    import pipeline.notify as notify_module

    assert not hasattr(notify_module, "smtplib")
    assert not hasattr(notify_module, "send_review_packet_ready")
