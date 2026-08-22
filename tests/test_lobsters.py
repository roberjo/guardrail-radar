"""Tests for connectors.lobsters — see docs/technical-spec.md §8.1, §18.

No live network calls — requests.Session is mocked. lobsters.py itself has
been live-tested against the real API (see CHANGELOG.md); this closes the
permanent-regression-test gap that manual testing doesn't.
"""

from unittest.mock import MagicMock, patch

import requests

from connectors.lobsters import _matches, fetch_items

TAGS = ["ai", "security"]
KEYWORDS = ["copilot", "fintech"]


def test_matches_on_tag_overlap():
    story = {"tags": ["ai", "python"], "title": "unrelated", "description": ""}
    assert _matches(story, TAGS, KEYWORDS) is True


def test_matches_on_keyword_in_title_or_description():
    assert _matches({"tags": [], "title": "Copilot news", "description": ""}, TAGS, KEYWORDS) is True
    assert _matches({"tags": [], "title": "x", "description": "fintech story"}, TAGS, KEYWORDS) is True


def test_no_match_without_tag_or_keyword_overlap():
    story = {"tags": ["hardware"], "title": "unrelated gadget", "description": "nothing relevant"}
    assert _matches(story, TAGS, KEYWORDS) is False


def _story(short_id, title, tags=None, url="https://example.com/story", score=1, comments=0):
    return {
        "short_id": short_id,
        "title": title,
        "tags": tags or ["ai"],
        "url": url,
        "score": score,
        "comment_count": comments,
        "created_at": "2026-01-01T00:00:00-06:00",
        "description": "",
    }


def _session_ctx(session):
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    return session


def test_fetch_items_dedupes_across_newest_and_hottest_feeds(monkeypatch):
    monkeypatch.setattr("connectors.lobsters._load_tags", lambda path="x": TAGS)
    monkeypatch.setattr("connectors.lobsters._load_keywords", lambda path="x": KEYWORDS)

    story = _story("abc1", "An AI story")
    session = _session_ctx(MagicMock())

    def _resp(stories):
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json.return_value = stories
        return r

    session.get.side_effect = [_resp([story]), _resp([story])]

    with (
        patch("connectors.lobsters.requests.Session", return_value=session),
        patch("connectors.lobsters.capture_excerpt", return_value=("an excerpt", "ok")),
    ):
        items = fetch_items()

    assert len(items) == 1


def test_fetch_items_skips_non_matching_stories(monkeypatch):
    monkeypatch.setattr("connectors.lobsters._load_tags", lambda path="x": TAGS)
    monkeypatch.setattr("connectors.lobsters._load_keywords", lambda path="x": KEYWORDS)

    matching = _story("m1", "AI story")
    non_matching = _story("n1", "gardening tips", tags=["gardening"])

    session = _session_ctx(MagicMock())
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = [matching, non_matching]
    session.get.return_value = resp

    with (
        patch("connectors.lobsters.requests.Session", return_value=session),
        patch("connectors.lobsters.capture_excerpt", return_value=("an excerpt", "ok")),
    ):
        items = fetch_items()

    assert len(items) == 1
    assert items[0].source_meta["short_id"] == "m1"


def test_fetch_items_falls_back_to_comments_url_when_no_external_url(monkeypatch):
    monkeypatch.setattr("connectors.lobsters._load_tags", lambda path="x": TAGS)
    monkeypatch.setattr("connectors.lobsters._load_keywords", lambda path="x": KEYWORDS)

    story = _story("m1", "AI story", url=None)
    story["comments_url"] = "https://lobste.rs/s/m1"

    session = _session_ctx(MagicMock())
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = [story]
    session.get.return_value = resp

    with (
        patch("connectors.lobsters.requests.Session", return_value=session),
        patch("connectors.lobsters.capture_excerpt", return_value=("an excerpt", "ok")),
    ):
        items = fetch_items()

    assert items[0].url == "https://lobste.rs/s/m1"


def test_fetch_items_continues_after_a_feed_failure(monkeypatch):
    monkeypatch.setattr("connectors.lobsters._load_tags", lambda path="x": TAGS)
    monkeypatch.setattr("connectors.lobsters._load_keywords", lambda path="x": KEYWORDS)

    session = _session_ctx(MagicMock())
    ok_resp = MagicMock()
    ok_resp.raise_for_status = MagicMock()
    ok_resp.json.return_value = [_story("ok1", "Still gets picked up")]
    session.get.side_effect = [requests.RequestException("boom"), ok_resp]

    with (
        patch("connectors.lobsters.requests.Session", return_value=session),
        patch("connectors.lobsters.capture_excerpt", return_value=("an excerpt", "ok")),
    ):
        items = fetch_items()

    assert len(items) == 1
