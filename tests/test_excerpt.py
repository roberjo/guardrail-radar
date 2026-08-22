"""Tests for pipeline.excerpt — see docs/technical-spec.md §6, §18.

No live network calls — every case mocks requests and DNS resolution.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from pipeline.excerpt import capture_excerpt, hn_comment_fallback


def _public_addrinfo(*_args, **_kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", 0))]  # example.com's old public IP


def _private_addrinfo(*_args, **_kwargs):
    return [(2, 1, 6, "", ("10.0.0.5", 0))]


@pytest.fixture(autouse=True)
def safe_host_by_default():
    with patch("pipeline.excerpt.socket.getaddrinfo", side_effect=_public_addrinfo):
        yield


def _html_response(html: str, content_type: str = "text/html"):
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"content-type": content_type}
    resp.text = html
    resp.raise_for_status = MagicMock()
    return resp


def test_primary_fetch_uses_og_description():
    html = '<html><head><meta property="og:description" content="The real og text"></head></html>'
    with patch("pipeline.excerpt.requests.get", return_value=_html_response(html)):
        excerpt, status = capture_excerpt("https://example.com/a")
    assert excerpt == "The real og text"
    assert status == "ok"


def test_primary_fetch_falls_back_to_meta_description():
    html = '<html><head><meta name="description" content="meta desc text"></head></html>'
    with patch("pipeline.excerpt.requests.get", return_value=_html_response(html)):
        excerpt, status = capture_excerpt("https://example.com/a")
    assert excerpt == "meta desc text"
    assert status == "ok"


def test_primary_fetch_falls_back_to_first_long_paragraph():
    html = (
        "<html><body><p>hi</p><p>"
        "a real paragraph that is long enough to clear the substantial-text threshold"
        "</p></body></html>"
    )
    with patch("pipeline.excerpt.requests.get", return_value=_html_response(html)):
        excerpt, status = capture_excerpt("https://example.com/a")
    assert "real paragraph" in excerpt
    assert status == "ok"


def test_paragraph_extraction_preserves_word_spacing_across_inline_tags():
    html = "<html><body><p>a <i>real</i> paragraph with <b>inline</b> tags in the middle of it</p></body></html>"
    with patch("pipeline.excerpt.requests.get", return_value=_html_response(html)):
        excerpt, _status = capture_excerpt("https://example.com/a")
    assert excerpt == "a real paragraph with inline tags in the middle of it"


def test_primary_fetch_failure_uses_fallback_text():
    with patch("pipeline.excerpt.requests.get", side_effect=requests.RequestException("boom")):
        excerpt, status = capture_excerpt("https://example.com/a", fallback_text="the selftext body")
    assert excerpt == "the selftext body"
    assert status == "partial"


def test_no_primary_and_no_fallback_yields_none_status():
    with patch("pipeline.excerpt.requests.get", side_effect=requests.RequestException("boom")):
        excerpt, status = capture_excerpt("https://example.com/a", fallback_text="   ")
    assert excerpt == ""
    assert status == "none"


def test_excerpt_truncated_to_max_chars():
    long_text = "x" * 5000
    html = f'<html><head><meta name="description" content="{long_text}"></head></html>'
    with patch("pipeline.excerpt.requests.get", return_value=_html_response(html)):
        excerpt, _status = capture_excerpt("https://example.com/a")
    assert len(excerpt) == 1000


def test_non_html_content_type_is_rejected():
    resp = _html_response("{}", content_type="application/json")
    with patch("pipeline.excerpt.requests.get", return_value=resp):
        excerpt, status = capture_excerpt("https://example.com/a.json", fallback_text="fallback here")
    assert status == "partial"
    assert excerpt == "fallback here"


def test_private_ip_host_is_refused_even_with_200_response():
    html = '<html><head><meta name="description" content="should never be used"></head></html>'
    with (
        patch("pipeline.excerpt.socket.getaddrinfo", side_effect=_private_addrinfo),
        patch("pipeline.excerpt.requests.get", return_value=_html_response(html)) as mock_get,
    ):
        excerpt, status = capture_excerpt("http://169.254.169.254/latest/meta-data/", fallback_text="fb")
    mock_get.assert_not_called()
    assert status == "partial"
    assert excerpt == "fb"


def test_non_http_scheme_is_refused():
    excerpt, status = capture_excerpt("ftp://example.com/file", fallback_text="fb")
    assert status == "partial"
    assert excerpt == "fb"


def test_hn_comment_fallback_extracts_first_child_text():
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"children": [{"text": "a <i>real</i> comment"}]}
    with patch("pipeline.excerpt.requests.get", return_value=resp):
        text = hn_comment_fallback("12345")
    assert text == "a real comment"


def test_hn_comment_fallback_handles_no_children():
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"children": []}
    with patch("pipeline.excerpt.requests.get", return_value=resp):
        text = hn_comment_fallback("12345")
    assert text == ""
