"""Tests for connectors.github — see docs/technical-spec.md §7.3, §18.

No live network calls — requests.Session is mocked. github.py itself has
been live-tested against the real API (see CHANGELOG.md), which is where
the star+json-needs-auth bug covered below was originally found.
"""

import os
from unittest.mock import MagicMock, patch

from connectors.github import (
    _headers,
    _readme_first_paragraph,
    _stars_last_7d,
    fetch_items,
)


def test_readme_first_paragraph_skips_headings_and_badges():
    content = "# Project Title\n\n![badge](x.svg)\n\nThe actual first real paragraph."
    assert _readme_first_paragraph(content) == "The actual first real paragraph."


def test_readme_first_paragraph_empty_when_nothing_usable():
    assert _readme_first_paragraph("# Title\n\n![badge](x.svg)\n\n[![another](y.svg)](z)") == ""


def test_headers_include_bearer_token_when_set():
    with patch.dict(os.environ, {"GH_SEARCH_TOKEN": "tok_123"}):
        headers = _headers()
    assert headers["Authorization"] == "Bearer tok_123"


def test_headers_omit_authorization_when_unset():
    with patch.dict(os.environ, {}, clear=True):
        headers = _headers()
    assert "Authorization" not in headers


def test_stars_last_7d_returns_zero_on_401_without_crashing():
    """Regression test: GitHub's star+json media type 401s even for public
    repos when unauthenticated — found via a live test run, not spec
    guesswork (see CHANGELOG.md). This must degrade gracefully, not raise."""
    import requests

    session = MagicMock()
    session.get.side_effect = requests.HTTPError("401 Unauthorized")

    count = _stars_last_7d("owner/repo", {}, session)
    assert count == 0


def test_stars_last_7d_counts_only_recent_stars():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    old = (now - timedelta(days=30)).isoformat().replace("+00:00", "Z")

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = [{"starred_at": recent}, {"starred_at": old}, {"starred_at": recent}]

    session = MagicMock()
    session.get.return_value = resp

    count = _stars_last_7d("owner/repo", {"Authorization": "Bearer tok"}, session)
    assert count == 2


def _repo(full_name, description="", pushed_at="2026-01-01T00:00:00Z", stars=0, issues=0):
    return {
        "full_name": full_name,
        "html_url": f"https://github.com/{full_name}",
        "description": description,
        "pushed_at": pushed_at,
        "created_at": pushed_at,
        "stargazers_count": stars,
        "open_issues_count": issues,
    }


def _search_response(repos):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"items": repos}
    return resp


def _readme_response(text="Some readme content."):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    import base64

    resp.json.return_value = {"content": base64.b64encode(text.encode()).decode()}
    return resp


def _session_ctx(session):
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    return session


def test_fetch_items_skips_star_lookups_entirely_when_unauthenticated(monkeypatch):
    monkeypatch.setattr(
        "connectors.github._load_config", lambda path="x": {"topics": ["ai-coding"], "window_days": 30}
    )
    repo = _repo("owner/repo")

    session = _session_ctx(MagicMock())
    session.get.side_effect = [_search_response([repo]), _readme_response()]

    with (
        patch.dict(os.environ, {}, clear=True),
        patch("connectors.github.requests.Session", return_value=session),
        patch("connectors.github.capture_excerpt", return_value=("an excerpt", "ok")),
    ):
        items = fetch_items()

    assert len(items) == 1
    assert items[0].raw_score == 0
    # Only 2 calls total (search + readme) — no stargazers call was ever made.
    assert session.get.call_count == 2


def test_fetch_items_uses_star_velocity_when_authenticated(monkeypatch):
    monkeypatch.setattr(
        "connectors.github._load_config", lambda path="x": {"topics": ["ai-coding"], "window_days": 30}
    )
    repo = _repo("owner/repo")

    stargazers_resp = MagicMock()
    stargazers_resp.raise_for_status = MagicMock()
    stargazers_resp.json.return_value = [{"starred_at": "2026-01-01T00:00:00Z"}]

    session = _session_ctx(MagicMock())
    session.get.side_effect = [_search_response([repo]), stargazers_resp, _readme_response()]

    with (
        patch.dict(os.environ, {"GH_SEARCH_TOKEN": "tok"}),
        patch("connectors.github.requests.Session", return_value=session),
        patch("connectors.github.capture_excerpt", return_value=("an excerpt", "ok")),
        patch("connectors.github.datetime") as mock_dt,
    ):
        # freeze "now" so the fixed starred_at above counts as recent
        from datetime import datetime, timezone

        mock_dt.now.return_value = datetime(2026, 1, 2, tzinfo=timezone.utc)
        mock_dt.fromisoformat = datetime.fromisoformat
        items = fetch_items()

    assert len(items) == 1
    assert items[0].raw_score == 1


def test_fetch_items_dedupes_repos_across_topics(monkeypatch):
    monkeypatch.setattr(
        "connectors.github._load_config",
        lambda path="x": {"topics": ["ai-coding", "llm-tools"], "window_days": 30},
    )
    repo = _repo("owner/repo")

    session = _session_ctx(MagicMock())
    session.get.side_effect = [
        _search_response([repo]),
        _readme_response(),
        _search_response([repo]),  # same repo shows up under the second topic
    ]

    with (
        patch.dict(os.environ, {}, clear=True),
        patch("connectors.github.requests.Session", return_value=session),
        patch("connectors.github.capture_excerpt", return_value=("an excerpt", "ok")),
        patch("connectors.github.time.sleep"),
    ):
        items = fetch_items()

    assert len(items) == 1


def test_fetch_items_continues_after_a_topic_search_failure(monkeypatch):
    import requests

    monkeypatch.setattr(
        "connectors.github._load_config",
        lambda path="x": {"topics": ["broken-topic", "ai-coding"], "window_days": 30},
    )
    repo = _repo("owner/repo")

    session = _session_ctx(MagicMock())
    session.get.side_effect = [
        requests.RequestException("boom"),
        _search_response([repo]),
        _readme_response(),
    ]

    with (
        patch.dict(os.environ, {}, clear=True),
        patch("connectors.github.requests.Session", return_value=session),
        patch("connectors.github.capture_excerpt", return_value=("an excerpt", "ok")),
        patch("connectors.github.time.sleep"),
    ):
        items = fetch_items()

    assert len(items) == 1
