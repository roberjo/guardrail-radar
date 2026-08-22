"""Tests for connectors.producthunt — see docs/technical-spec.md §8.2, §18.

No live network calls, no real credentials. Covers the pure helpers
directly and fetch_items end-to-end against a mocked Session, including
pagination and the topic filter.
"""

import os
from unittest.mock import MagicMock, patch

from connectors.producthunt import _first_paragraph, fetch_items


def test_first_paragraph_returns_only_first_block():
    text = "First paragraph here.\n\nSecond paragraph should not be included."
    assert _first_paragraph(text) == "First paragraph here."


def test_first_paragraph_skips_leading_blank_blocks():
    text = "\n\n  \n\nActual first paragraph."
    assert _first_paragraph(text) == "Actual first paragraph."


def test_first_paragraph_empty_input():
    assert _first_paragraph("") == ""


def _node(id_, name, topics, tagline="", description="", votes=0, comments=0):
    return {
        "id": id_,
        "name": name,
        "tagline": tagline,
        "description": description,
        "url": f"https://producthunt.example.com/{id_}",
        "votesCount": votes,
        "commentsCount": comments,
        "createdAt": "2026-01-01T00:00:00Z",
        "topics": {"edges": [{"node": {"slug": t}} for t in topics]},
    }


def _graphql_response(nodes: list[dict], has_next_page: bool = False, end_cursor: str | None = None):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "data": {
            "posts": {
                "edges": [{"node": n} for n in nodes],
                "pageInfo": {"hasNextPage": has_next_page, "endCursor": end_cursor},
            }
        }
    }
    return resp


def _session_ctx(session):
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    return session


def test_fetch_items_filters_by_topic(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "connectors.producthunt._load_config",
        lambda path="x": {"topics": ["artificial-intelligence"], "window_days": 7},
    )
    matching = _node("1", "AI dev tool", ["artificial-intelligence"], votes=10)
    non_matching = _node("2", "Unrelated gadget", ["hardware"], votes=100)

    session = _session_ctx(MagicMock())
    session.post.return_value = _graphql_response([matching, non_matching])

    with (
        patch.dict(os.environ, {"PRODUCTHUNT_TOKEN": "tok"}),
        patch("connectors.producthunt.requests.Session", return_value=session),
        patch("connectors.producthunt.capture_excerpt", return_value=("an excerpt", "ok")),
    ):
        items = fetch_items()

    assert len(items) == 1
    assert items[0].title == "AI dev tool"
    assert items[0].raw_score == 10


def test_fetch_items_no_topic_filter_when_none_configured(monkeypatch):
    monkeypatch.setattr(
        "connectors.producthunt._load_config", lambda path="x": {"topics": [], "window_days": 7}
    )
    node = _node("1", "Anything at all", ["hardware"])

    session = _session_ctx(MagicMock())
    session.post.return_value = _graphql_response([node])

    with (
        patch.dict(os.environ, {"PRODUCTHUNT_TOKEN": "tok"}),
        patch("connectors.producthunt.requests.Session", return_value=session),
        patch("connectors.producthunt.capture_excerpt", return_value=("an excerpt", "ok")),
    ):
        items = fetch_items()

    assert len(items) == 1


def test_fetch_items_follows_pagination(monkeypatch):
    monkeypatch.setattr(
        "connectors.producthunt._load_config", lambda path="x": {"topics": [], "window_days": 7}
    )
    page1 = _node("1", "First page item", [])
    page2 = _node("2", "Second page item", [])

    session = _session_ctx(MagicMock())
    session.post.side_effect = [
        _graphql_response([page1], has_next_page=True, end_cursor="cursor-1"),
        _graphql_response([page2], has_next_page=False),
    ]

    with (
        patch.dict(os.environ, {"PRODUCTHUNT_TOKEN": "tok"}),
        patch("connectors.producthunt.requests.Session", return_value=session),
        patch("connectors.producthunt.capture_excerpt", return_value=("an excerpt", "ok")),
    ):
        items = fetch_items()

    assert {i.title for i in items} == {"First page item", "Second page item"}
    assert session.post.call_count == 2
    second_call_variables = session.post.call_args_list[1].kwargs["json"]["variables"]
    assert second_call_variables["after"] == "cursor-1"


def test_fetch_items_queries_once_per_configured_topic_and_dedupes(monkeypatch):
    monkeypatch.setattr(
        "connectors.producthunt._load_config",
        lambda path="x": {"topics": ["topic-a", "topic-b"], "window_days": 7},
    )
    shared = _node("1", "Shows up under both topics", ["topic-a", "topic-b"])
    only_b = _node("2", "Only under topic-b", ["topic-b"])

    session = _session_ctx(MagicMock())
    session.post.side_effect = [
        _graphql_response([shared]),
        _graphql_response([shared, only_b]),
    ]

    with (
        patch.dict(os.environ, {"PRODUCTHUNT_TOKEN": "tok"}),
        patch("connectors.producthunt.requests.Session", return_value=session),
        patch("connectors.producthunt.capture_excerpt", return_value=("an excerpt", "ok")),
    ):
        items = fetch_items()

    assert session.post.call_count == 2
    first_variables = session.post.call_args_list[0].kwargs["json"]["variables"]
    second_variables = session.post.call_args_list[1].kwargs["json"]["variables"]
    assert first_variables["topic"] == "topic-a"
    assert second_variables["topic"] == "topic-b"
    assert {i.title for i in items} == {"Shows up under both topics", "Only under topic-b"}
    assert len(items) == 2  # "1" from the topic-b query is deduped, not doubled


def test_fetch_items_falls_back_to_single_global_query_when_no_topics_configured(monkeypatch):
    monkeypatch.setattr(
        "connectors.producthunt._load_config", lambda path="x": {"topics": [], "window_days": 7}
    )
    node = _node("1", "Anything at all", ["hardware"])

    session = _session_ctx(MagicMock())
    session.post.return_value = _graphql_response([node])

    with (
        patch.dict(os.environ, {"PRODUCTHUNT_TOKEN": "tok"}),
        patch("connectors.producthunt.requests.Session", return_value=session),
        patch("connectors.producthunt.capture_excerpt", return_value=("an excerpt", "ok")),
    ):
        items = fetch_items()

    assert session.post.call_count == 1
    assert session.post.call_args.kwargs["json"]["variables"]["topic"] is None
    assert len(items) == 1


def test_fetch_items_skips_post_with_missing_url(monkeypatch):
    monkeypatch.setattr(
        "connectors.producthunt._load_config", lambda path="x": {"topics": [], "window_days": 7}
    )
    no_url_node = _node("1", "Missing its url", [])
    del no_url_node["url"]
    good_node = _node("2", "Has a url", [])

    session = _session_ctx(MagicMock())
    session.post.return_value = _graphql_response([no_url_node, good_node])

    with (
        patch.dict(os.environ, {"PRODUCTHUNT_TOKEN": "tok"}),
        patch("connectors.producthunt.requests.Session", return_value=session),
        patch("connectors.producthunt.capture_excerpt", return_value=("an excerpt", "ok")),
    ):
        items = fetch_items()

    assert len(items) == 1
    assert items[0].title == "Has a url"


def test_fetch_items_continues_past_partial_graphql_errors_when_data_present(monkeypatch):
    monkeypatch.setattr(
        "connectors.producthunt._load_config", lambda path="x": {"topics": [], "window_days": 7}
    )
    node = _node("1", "Still usable despite a partial error", [])

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "data": {
            "posts": {
                "edges": [{"node": node}],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        },
        "errors": [{"message": "field resolver error on an unrelated node"}],
    }

    session = _session_ctx(MagicMock())
    session.post.return_value = resp

    with (
        patch.dict(os.environ, {"PRODUCTHUNT_TOKEN": "tok"}),
        patch("connectors.producthunt.requests.Session", return_value=session),
        patch("connectors.producthunt.capture_excerpt", return_value=("an excerpt", "ok")),
    ):
        items = fetch_items()

    assert len(items) == 1
    assert items[0].title == "Still usable despite a partial error"


def test_fetch_items_stops_on_graphql_errors(monkeypatch):
    monkeypatch.setattr(
        "connectors.producthunt._load_config", lambda path="x": {"topics": [], "window_days": 7}
    )
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"errors": [{"message": "invalid token"}]}

    session = _session_ctx(MagicMock())
    session.post.return_value = resp

    with (
        patch.dict(os.environ, {"PRODUCTHUNT_TOKEN": "tok"}),
        patch("connectors.producthunt.requests.Session", return_value=session),
    ):
        items = fetch_items()

    assert items == []
