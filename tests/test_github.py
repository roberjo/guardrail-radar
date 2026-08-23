"""Tests for connectors.github — see docs/technical-spec.md §7.3, §18.

No live network calls — requests.Session is mocked. github.py itself has
been live-tested against the real API (see CHANGELOG.md), which is where
the per-repo stargazers-endpoint restriction covered below was found.
"""

import math
import os
from unittest.mock import MagicMock, patch

from connectors.github import (
    STAR_SCALE,
    _headers,
    _readme_first_paragraph,
    _star_score,
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


def test_star_score_is_zero_for_zero_stars():
    assert _star_score(0) == 0


def test_star_score_is_monotonic():
    assert _star_score(10) < _star_score(1000) < _star_score(100_000) < _star_score(250_000)


def test_star_score_matches_log_scale_formula():
    assert _star_score(1000) == int(math.log1p(1000) * STAR_SCALE)


def test_star_score_compresses_huge_counts_into_hn_comparable_range():
    # torvalds/linux-scale star counts must not swamp HN/Reddit-scale
    # raw_score in the shared velocity formula (pipeline/score.py) — see
    # the module docstring for why. A three-digit result is "comparable to
    # a very hot HN post's points," not "orders of magnitude larger."
    assert _star_score(250_000) < 1500


def test_star_score_never_negative_on_bad_input():
    assert _star_score(-5) == 0


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


def test_fetch_items_uses_search_result_star_count_directly(monkeypatch):
    # No separate stargazers-endpoint call at all now — total_stars comes
    # straight off the search result, which is also why this needs no
    # GH_SEARCH_TOKEN to produce a meaningful (nonzero) raw_score, unlike
    # the old per-repo velocity lookup.
    monkeypatch.setattr(
        "connectors.github._load_config", lambda path="x": {"topics": ["ai-coding"], "window_days": 30}
    )
    repo = _repo("owner/repo", stars=1000)

    session = _session_ctx(MagicMock())
    session.get.side_effect = [_search_response([repo]), _readme_response()]

    with (
        patch.dict(os.environ, {}, clear=True),
        patch("connectors.github.requests.Session", return_value=session),
        patch("connectors.github.capture_excerpt", return_value=("an excerpt", "ok")),
    ):
        items = fetch_items()

    assert len(items) == 1
    assert items[0].raw_score == _star_score(1000)
    assert items[0].source_meta["total_stars"] == 1000
    # Only 2 calls total (search + readme) — no stargazers call is ever made.
    assert session.get.call_count == 2


def test_fetch_items_handles_missing_stargazers_count(monkeypatch):
    monkeypatch.setattr(
        "connectors.github._load_config", lambda path="x": {"topics": ["ai-coding"], "window_days": 30}
    )
    repo = _repo("owner/repo")
    del repo["stargazers_count"]

    session = _session_ctx(MagicMock())
    session.get.side_effect = [_search_response([repo]), _readme_response()]

    with (
        patch.dict(os.environ, {}, clear=True),
        patch("connectors.github.requests.Session", return_value=session),
        patch("connectors.github.capture_excerpt", return_value=("an excerpt", "ok")),
    ):
        items = fetch_items()

    assert items[0].raw_score == 0


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
