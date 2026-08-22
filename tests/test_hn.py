"""Tests for connectors.hn — see docs/technical-spec.md §7.1, §18.

No live network calls — requests.Session is mocked. hn.py itself has been
live-tested against the real API (see CHANGELOG.md); this closes the
permanent-regression-test gap that manual testing doesn't.
"""

from unittest.mock import MagicMock, patch

from connectors.hn import fetch_items


def _hit(object_id, title, url=None, points=1, comments=0, story_text=None):
    hit = {
        "objectID": object_id,
        "title": title,
        "url": url,
        "points": points,
        "num_comments": comments,
        "created_at": "2026-01-01T00:00:00Z",
        "author": "someone",
    }
    if story_text is not None:
        hit["story_text"] = story_text
    return hit


def _search_response(hits):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"hits": hits}
    return resp


def _session_ctx(session):
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    return session


def test_fetch_items_merges_results_across_terms_deduped():
    shared_hit = _hit("1", "Copilot and Cursor both mentioned here")
    only_in_second_term = _hit("2", "Only matches the second term")

    session = _session_ctx(MagicMock())
    session.get.side_effect = [
        _search_response([shared_hit]),
        _search_response([shared_hit, only_in_second_term]),  # same id "1" again
    ]

    with (
        patch("connectors.hn.requests.Session", return_value=session),
        patch("connectors.hn.capture_excerpt", return_value=("an excerpt", "ok")),
        patch("connectors.hn.time.sleep"),
    ):
        items = fetch_items(terms=["copilot", "cursor"])

    assert {i.source_meta["object_id"] for i in items} == {"1", "2"}
    assert len(items) == 2  # id "1" from the second query is deduped, not doubled


def test_fetch_items_falls_back_to_hn_item_url_when_no_external_url():
    hit = _hit("42", "Ask HN: something", url=None)

    session = _session_ctx(MagicMock())
    session.get.return_value = _search_response([hit])

    with (
        patch("connectors.hn.requests.Session", return_value=session),
        patch("connectors.hn.capture_excerpt", return_value=("an excerpt", "ok")),
    ):
        items = fetch_items(terms=["copilot"])

    assert items[0].url == "https://news.ycombinator.com/item?id=42"


def test_fetch_items_uses_hn_comment_fallback_when_excerpt_capture_fails():
    hit = _hit("42", "A story with no usable page text")

    session = _session_ctx(MagicMock())
    session.get.return_value = _search_response([hit])

    with (
        patch("connectors.hn.requests.Session", return_value=session),
        patch("connectors.hn.capture_excerpt", return_value=("", "none")),
        patch("connectors.hn.hn_comment_fallback", return_value="the top comment's text"),
    ):
        items = fetch_items(terms=["copilot"])

    assert items[0].excerpt == "the top comment's text"
    assert items[0].excerpt_status == "partial"


def test_fetch_items_skips_comment_fallback_when_excerpt_already_succeeded():
    hit = _hit("42", "A story with a good page")

    session = _session_ctx(MagicMock())
    session.get.return_value = _search_response([hit])

    with (
        patch("connectors.hn.requests.Session", return_value=session),
        patch("connectors.hn.capture_excerpt", return_value=("a real excerpt", "ok")),
        patch("connectors.hn.hn_comment_fallback") as mock_comment_fallback,
    ):
        items = fetch_items(terms=["copilot"])

    mock_comment_fallback.assert_not_called()
    assert items[0].excerpt == "a real excerpt"


def test_fetch_items_continues_after_a_query_failure():
    import requests

    session = _session_ctx(MagicMock())
    session.get.side_effect = [
        requests.RequestException("boom"),
        _search_response([_hit("1", "Still gets picked up")]),
    ]

    with (
        patch("connectors.hn.requests.Session", return_value=session),
        patch("connectors.hn.capture_excerpt", return_value=("an excerpt", "ok")),
        patch("connectors.hn.time.sleep"),
    ):
        items = fetch_items(terms=["copilot", "cursor"])

    assert len(items) == 1
