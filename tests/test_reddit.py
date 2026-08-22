"""Tests for connectors.reddit — see docs/technical-spec.md §7.2, §18.

No live network calls, no real credentials. Covers the pure helpers
directly and fetch_items end-to-end against a mocked Session.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from connectors.reddit import _matches, _parse_listing, fetch_items, get_token

KEYWORDS = ["copilot", "fintech"]


def test_matches_checks_title_and_selftext():
    assert _matches({"title": "Copilot rollout at a bank", "selftext": ""}, KEYWORDS) is True
    assert _matches({"title": "unrelated", "selftext": "we adopted copilot last week"}, KEYWORDS) is True
    assert _matches({"title": "unrelated", "selftext": "still unrelated"}, KEYWORDS) is False


def test_matches_is_case_insensitive():
    assert _matches({"title": "COPILOT news", "selftext": ""}, KEYWORDS) is True


def test_parse_listing_splits_path_and_query():
    path, params = _parse_listing("top?t=week")
    assert path == "top"
    assert params == {"t": "week"}


def test_parse_listing_handles_bare_path():
    path, params = _parse_listing("new")
    assert path == "new"
    assert params == {}


def test_get_token_posts_client_credentials_and_returns_token():
    session = MagicMock()
    session.post.return_value.json.return_value = {"access_token": "tok_123"}
    session.post.return_value.raise_for_status = MagicMock()

    with patch.dict(os.environ, {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "secret"}):
        token = get_token(session)

    assert token == "tok_123"
    call = session.post.call_args
    assert call.kwargs["auth"] == ("id", "secret")
    assert call.kwargs["data"] == {"grant_type": "client_credentials"}


def _listing_response(posts: list[dict]):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"data": {"children": [{"data": p} for p in posts]}}
    return resp


@pytest.fixture
def config(monkeypatch, tmp_path):
    keywords_path = tmp_path / "keywords.yml"
    sources_path = tmp_path / "sources.yml"
    keywords_path.write_text("core_terms: [copilot]\ncontext_terms: [fintech]\n")
    sources_path.write_text("reddit:\n  subreddits: [fintech]\n  listings: [new]\n")
    monkeypatch.setattr("connectors.reddit._load_config", lambda path="x": (["fintech"], ["new"]))
    monkeypatch.setattr("connectors.reddit._load_keywords", lambda path="x": ["copilot", "fintech"])


def test_fetch_items_filters_and_normalizes(config, monkeypatch):
    matching_post = {
        "id": "abc123",
        "title": "Bank rolls out Copilot for fintech engineers",
        "selftext": "",
        "is_self": False,
        "url": "https://example.com/story",
        "ups": 42,
        "num_comments": 7,
        "created_utc": 1700000000,
    }
    non_matching_post = {
        "id": "xyz789",
        "title": "completely unrelated gardening post",
        "selftext": "",
        "is_self": True,
        "permalink": "/r/fintech/comments/xyz789/gardening/",
        "ups": 1,
        "num_comments": 0,
        "created_utc": 1700000000,
    }

    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    session.post.return_value.json.return_value = {"access_token": "tok"}
    session.post.return_value.raise_for_status = MagicMock()
    session.get.return_value = _listing_response([matching_post, non_matching_post])

    with (
        patch.dict(os.environ, {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "secret"}),
        patch("connectors.reddit.requests.Session", return_value=session),
        patch("connectors.reddit.capture_excerpt", return_value=("an excerpt", "ok")),
        patch("connectors.reddit.time.sleep"),
    ):
        items = fetch_items()

    assert len(items) == 1
    item = items[0]
    assert item.source == "reddit"
    assert item.raw_score == 42
    assert item.comment_count == 7
    assert item.excerpt == "an excerpt"
    assert item.source_meta["subreddit"] == "fintech"


def test_fetch_items_dedupes_by_post_id(config, monkeypatch):
    post = {
        "id": "dup1",
        "title": "Copilot news for fintech",
        "selftext": "",
        "is_self": False,
        "url": "https://example.com/a",
        "ups": 5,
        "num_comments": 1,
        "created_utc": 1700000000,
    }
    monkeypatch.setattr(
        "connectors.reddit._load_config", lambda path="x": (["fintech"], ["new", "top?t=week"])
    )

    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    session.post.return_value.json.return_value = {"access_token": "tok"}
    session.post.return_value.raise_for_status = MagicMock()
    session.get.return_value = _listing_response([post])

    with (
        patch.dict(os.environ, {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "secret"}),
        patch("connectors.reddit.requests.Session", return_value=session),
        patch("connectors.reddit.capture_excerpt", return_value=("an excerpt", "ok")),
        patch("connectors.reddit.time.sleep"),
    ):
        items = fetch_items()

    # Same post_id appears in both the "new" and "top" listings — must not duplicate.
    assert len(items) == 1


def test_fetch_items_passes_raw_json_on_listing_request(config, monkeypatch):
    post = {
        "id": "abc123",
        "title": "Bank rolls out Copilot for fintech engineers",
        "selftext": "",
        "is_self": False,
        "url": "https://example.com/story",
        "ups": 42,
        "num_comments": 7,
        "created_utc": 1700000000,
    }

    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    session.post.return_value.json.return_value = {"access_token": "tok"}
    session.post.return_value.raise_for_status = MagicMock()
    session.get.return_value = _listing_response([post])

    with (
        patch.dict(os.environ, {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "secret"}),
        patch("connectors.reddit.requests.Session", return_value=session),
        patch("connectors.reddit.capture_excerpt", return_value=("an excerpt", "ok")),
        patch("connectors.reddit.time.sleep"),
    ):
        fetch_items()

    assert session.get.call_args.kwargs["params"]["raw_json"] == 1


def test_fetch_items_treats_removed_and_deleted_selftext_as_no_fallback(config, monkeypatch):
    removed_post = {
        "id": "removed1",
        "title": "Copilot fintech post that got removed",
        "selftext": "[removed]",
        "is_self": True,
        "permalink": "/r/fintech/comments/removed1/x/",
        "ups": 1,
        "num_comments": 0,
        "created_utc": 1700000000,
    }

    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    session.post.return_value.json.return_value = {"access_token": "tok"}
    session.post.return_value.raise_for_status = MagicMock()
    session.get.return_value = _listing_response([removed_post])

    with (
        patch.dict(os.environ, {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "secret"}),
        patch("connectors.reddit.requests.Session", return_value=session),
        patch("connectors.reddit.capture_excerpt") as mock_capture_excerpt,
        patch("connectors.reddit.time.sleep"),
    ):
        mock_capture_excerpt.return_value = ("", "none")
        fetch_items()

    assert mock_capture_excerpt.call_args.kwargs["fallback_text"] == ""


def test_fetch_items_uses_comment_fallback_for_link_post_with_no_excerpt(config, monkeypatch):
    link_post = {
        "id": "link1",
        "title": "Bank ships Copilot for fintech team",
        "selftext": "",
        "is_self": False,
        "url": "https://example.com/story",
        "ups": 9,
        "num_comments": 3,
        "created_utc": 1700000000,
    }

    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    session.post.return_value.json.return_value = {"access_token": "tok"}
    session.post.return_value.raise_for_status = MagicMock()
    session.get.return_value = _listing_response([link_post])

    with (
        patch.dict(os.environ, {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "secret"}),
        patch("connectors.reddit.requests.Session", return_value=session),
        patch("connectors.reddit.capture_excerpt", return_value=("", "none")),
        patch("connectors.reddit._comment_fallback", return_value="the top comment's body") as mock_fallback,
        patch("connectors.reddit.time.sleep"),
    ):
        items = fetch_items()

    assert mock_fallback.call_args.args[:2] == ("fintech", "link1")
    assert items[0].excerpt == "Bank ships Copilot for fintech team the top comment's body"
    assert items[0].excerpt_status == "partial"


def test_fetch_items_skips_comment_fallback_for_self_posts(config, monkeypatch):
    self_post = {
        "id": "self1",
        "title": "Copilot fintech discussion",
        "selftext": "[deleted]",
        "is_self": True,
        "permalink": "/r/fintech/comments/self1/x/",
        "ups": 2,
        "num_comments": 0,
        "created_utc": 1700000000,
    }

    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    session.post.return_value.json.return_value = {"access_token": "tok"}
    session.post.return_value.raise_for_status = MagicMock()
    session.get.return_value = _listing_response([self_post])

    with (
        patch.dict(os.environ, {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "secret"}),
        patch("connectors.reddit.requests.Session", return_value=session),
        patch("connectors.reddit.capture_excerpt", return_value=("", "none")),
        patch("connectors.reddit._comment_fallback") as mock_fallback,
        patch("connectors.reddit.time.sleep"),
    ):
        fetch_items()

    mock_fallback.assert_not_called()


def test_fetch_items_continues_after_malformed_json_response(config, monkeypatch):
    monkeypatch.setattr(
        "connectors.reddit._load_config", lambda path="x": (["fintech"], ["new", "top?t=week"])
    )
    good_post = {
        "id": "good1",
        "title": "Copilot fintech news that parses fine",
        "selftext": "",
        "is_self": False,
        "url": "https://example.com/story",
        "ups": 3,
        "num_comments": 1,
        "created_utc": 1700000000,
    }

    bad_resp = MagicMock()
    bad_resp.raise_for_status = MagicMock()
    bad_resp.json.side_effect = ValueError("not json")

    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    session.post.return_value.json.return_value = {"access_token": "tok"}
    session.post.return_value.raise_for_status = MagicMock()
    session.get.side_effect = [bad_resp, _listing_response([good_post])]

    with (
        patch.dict(os.environ, {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "secret"}),
        patch("connectors.reddit.requests.Session", return_value=session),
        patch("connectors.reddit.capture_excerpt", return_value=("an excerpt", "ok")),
        patch("connectors.reddit.time.sleep"),
    ):
        items = fetch_items()

    assert len(items) == 1
    assert items[0].source_meta["post_id"] == "good1"
