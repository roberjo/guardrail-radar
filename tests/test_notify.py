"""Tests for pipeline.notify — see docs/technical-spec.md §15.2, §18.

No live GitHub API calls — requests.post is mocked. Confirms this stays an
internal maintainer notification (a GitHub Issue in this repo), never a
subscriber-facing send.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from pipeline.notify import _ranked_count, send_review_packet_ready


def _env(**extra):
    base = {"GITHUB_TOKEN": "tok_123", "GITHUB_REPOSITORY": "someuser/guardrail-radar"}
    base.update(extra)
    return base


def test_opens_a_github_issue_via_the_rest_api():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()

    with (
        patch.dict(os.environ, _env(), clear=False),
        patch("pipeline.notify.requests.post", return_value=resp) as mock_post,
    ):
        send_review_packet_ready("2026-W01", 12)

    mock_post.assert_called_once()
    url, kwargs = mock_post.call_args.args[0], mock_post.call_args.kwargs
    assert url == "https://api.github.com/repos/someuser/guardrail-radar/issues"
    assert kwargs["headers"]["Authorization"] == "Bearer tok_123"
    assert kwargs["headers"]["Accept"] == "application/vnd.github+json"
    payload = kwargs["json"]
    assert "2026-W01" in payload["title"]
    assert payload["labels"] == ["review-packet"]
    assert "assignees" not in payload
    resp.raise_for_status.assert_called_once()


def test_issue_body_mentions_item_count_and_review_packet_path():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()

    with (
        patch.dict(os.environ, _env(), clear=False),
        patch("pipeline.notify.requests.post", return_value=resp) as mock_post,
    ):
        send_review_packet_ready("2026-W07", 9)

    payload = mock_post.call_args.kwargs["json"]
    assert "9 candidates" in payload["body"]
    assert "2026-W07" in payload["body"]
    assert "digest/review/2026-W07.md" in payload["body"]


def test_assigns_maintainer_when_username_configured():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()

    with (
        patch.dict(os.environ, _env(MAINTAINER_GITHUB_USERNAME="octocat"), clear=False),
        patch("pipeline.notify.requests.post", return_value=resp) as mock_post,
    ):
        send_review_packet_ready("2026-W01", 3)

    payload = mock_post.call_args.kwargs["json"]
    assert payload["assignees"] == ["octocat"]


def test_never_sends_to_a_subscriber_or_email_address():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()

    with (
        patch.dict(os.environ, _env(), clear=False),
        patch("pipeline.notify.requests.post", return_value=resp) as mock_post,
    ):
        send_review_packet_ready("2026-W01", 1)

    payload = mock_post.call_args.kwargs["json"]
    # An internal repo issue has no email recipient concept at all —
    # confirm no such field ever gets attached to the request.
    assert "to" not in payload
    assert "cc" not in payload
    assert "bcc" not in payload


def test_missing_ranked_file_raises_instead_of_reporting_zero_candidates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError, match="2026-W99"):
        _ranked_count("2026-W99")


def test_missing_ranked_file_never_opens_a_misleading_issue(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with (
        patch.dict(os.environ, _env(), clear=False),
        patch("pipeline.notify.requests.post") as mock_post,
        pytest.raises(FileNotFoundError),
    ):
        send_review_packet_ready("2026-W99", _ranked_count("2026-W99"))

    mock_post.assert_not_called()
