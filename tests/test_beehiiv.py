"""Tests for pipeline.beehiiv — see .claude/skills/beehiiv-api/SKILL.md.

No live network calls, no real credentials. The core thing under test is
the safety behavior: create_draft_post must always request status="draft"
and must hard-fail (never silently succeed) if the post that actually got
created isn't a draft, or never finishes creating.
"""

from unittest.mock import MagicMock, patch

import pytest

from pipeline.beehiiv import (
    BeehiivError,
    create_draft_post,
    get_post,
    get_publication,
    list_posts,
    push_draft,
)


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("BEEHIIV_API_KEY", "test-key")


def _response(status_code=200, json_data=None, content=b"{}"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import requests
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error")
    return resp


def test_headers_raise_without_api_key(monkeypatch):
    monkeypatch.delenv("BEEHIIV_API_KEY", raising=False)
    with pytest.raises(BeehiivError):
        get_publication()


@patch("pipeline.beehiiv.requests.get")
def test_get_publication_requests_stats_expansion(mock_get):
    mock_get.return_value = _response(json_data={"data": {"id": "pub_x", "stats": {"active_subscriptions": 42}}})
    data = get_publication()
    assert data["stats"]["active_subscriptions"] == 42
    assert mock_get.call_args.kwargs["params"] == {"expand[]": "stats"}
    assert "Bearer test-key" in mock_get.call_args.kwargs["headers"]["Authorization"]


@patch("pipeline.beehiiv.requests.get")
def test_get_publication_without_stats_omits_expand_param(mock_get):
    mock_get.return_value = _response(json_data={"data": {"id": "pub_x"}})
    get_publication(expand_stats=False)
    assert mock_get.call_args.kwargs["params"] == {}


@patch("pipeline.beehiiv.requests.get")
def test_list_posts_returns_data_list(mock_get):
    mock_get.return_value = _response(json_data={"data": [{"id": "post_1"}, {"id": "post_2"}]})
    posts = list_posts()
    assert [p["id"] for p in posts] == ["post_1", "post_2"]


@patch("pipeline.beehiiv.requests.get")
def test_get_post_pending_returns_sentinel_not_error(mock_get):
    mock_get.return_value = _response(status_code=202)
    assert get_post("post_1") == {"status": "_pending"}


@patch("pipeline.beehiiv.requests.get")
def test_get_post_creation_failed_raises(mock_get):
    mock_get.return_value = _response(status_code=404, json_data={"error": "POST_CREATION_FAILED"}, content=b'{"error": "POST_CREATION_FAILED"}')
    with pytest.raises(BeehiivError, match="failed to create"):
        get_post("post_1")


@patch("pipeline.beehiiv.time.sleep")
@patch("pipeline.beehiiv.requests.get")
@patch("pipeline.beehiiv.requests.post")
def test_create_draft_post_always_sends_status_draft(mock_post, mock_get, _mock_sleep):
    mock_post.return_value = _response(status_code=201, json_data={"data": {"id": "post_1"}})
    mock_get.return_value = _response(json_data={"data": {"id": "post_1", "status": "draft"}})

    create_draft_post("A title", "<p>body</p>")

    assert mock_post.call_args.kwargs["json"]["status"] == "draft"


@patch("pipeline.beehiiv.time.sleep")
@patch("pipeline.beehiiv.requests.get")
@patch("pipeline.beehiiv.requests.post")
def test_create_draft_post_polls_through_pending_state(mock_post, mock_get, mock_sleep):
    mock_post.return_value = _response(status_code=201, json_data={"data": {"id": "post_1"}})
    mock_get.side_effect = [
        _response(status_code=202),
        _response(json_data={"data": {"id": "post_1", "status": "draft"}}),
    ]

    post = create_draft_post("A title", "<p>body</p>")

    assert post["status"] == "draft"
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once()


@patch("pipeline.beehiiv.time.sleep")
@patch("pipeline.beehiiv.requests.get")
@patch("pipeline.beehiiv.requests.post")
def test_create_draft_post_raises_if_final_status_is_not_draft(mock_post, mock_get, _mock_sleep):
    # The core safety case: if Beehiiv's response ever disagrees with the
    # draft status this module explicitly requested, this must be a loud
    # failure, never a silent success — see create_draft_post's docstring.
    mock_post.return_value = _response(status_code=201, json_data={"data": {"id": "post_1"}})
    mock_get.return_value = _response(json_data={"data": {"id": "post_1", "status": "confirmed"}})

    with pytest.raises(BeehiivError, match="not 'draft'"):
        create_draft_post("A title", "<p>body</p>")


@patch("pipeline.beehiiv.time.sleep")
@patch("pipeline.beehiiv.requests.get")
@patch("pipeline.beehiiv.requests.post")
def test_create_draft_post_raises_if_still_pending_after_max_polls(mock_post, mock_get, mock_sleep):
    mock_post.return_value = _response(status_code=201, json_data={"data": {"id": "post_1"}})
    mock_get.return_value = _response(status_code=202)

    with pytest.raises(BeehiivError, match="still being created"):
        create_draft_post("A title", "<p>body</p>")


@patch("pipeline.beehiiv.create_draft_post")
@patch("pipeline.render.build_beehiiv_draft_content")
def test_push_draft_uses_render_content_for_the_post(mock_build, mock_create):
    mock_build.return_value = ("A subject", "<p>body</p>")
    mock_create.return_value = {"id": "post_1", "status": "draft"}

    result = push_draft("2026-W34")

    mock_build.assert_called_once_with("2026-W34")
    mock_create.assert_called_once_with("A subject", "<p>body</p>")
    assert result["status"] == "draft"
