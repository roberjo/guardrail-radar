"""Tests for pipeline.verify — see docs/technical-spec.md §13, §18.

No live network calls — link resolution is mocked at the requests.head/get
boundary; DNS resolution is mocked to always look like a public host.
"""

from unittest.mock import MagicMock, patch

from pipeline.verify import _fuzzy_contains, check_link, verify_entry

RANKED = {
    "c1": {
        "cluster_id": "c1",
        "title": "Real story",
        "url": "https://example.com/a",
        "cluster_excerpt": "the vendor announced a new SOC 2 Type II report available on request",
    }
}


def _ok_response(status=200):
    resp = MagicMock()
    resp.status_code = status
    return resp


@patch("pipeline.verify.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))])
def test_check_link_ok_on_200(_mock_dns):
    with patch("pipeline.verify.requests.head", return_value=_ok_response(200)):
        ok, detail = check_link("https://example.com/a")
    assert ok is True
    assert "200" in detail


@patch("pipeline.verify.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))])
def test_check_link_blocked_on_404(_mock_dns):
    # A >=400 HEAD response also retries via GET (some sites block HEAD but
    # serve GET fine) — a genuinely dead link 404s both ways.
    with (
        patch("pipeline.verify.requests.head", return_value=_ok_response(404)),
        patch("pipeline.verify.requests.get", return_value=_ok_response(404)),
    ):
        ok, detail = check_link("https://example.com/missing")
    assert ok is False
    assert "404" in detail


@patch("pipeline.verify.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))])
def test_check_link_falls_back_to_get_on_405(_mock_dns):
    head_resp = _ok_response(405)
    get_resp = _ok_response(200)
    with (
        patch("pipeline.verify.requests.head", return_value=head_resp),
        patch("pipeline.verify.requests.get", return_value=get_resp),
    ):
        ok, _detail = check_link("https://example.com/head-not-allowed")
    assert ok is True


@patch("pipeline.verify.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))])
def test_check_link_closes_the_streamed_get_fallback_response(_mock_dns):
    # The GET fallback is opened with stream=True (we only need the status
    # line), so it must be explicitly closed — otherwise the connection is
    # never released back to the pool.
    head_resp = _ok_response(405)
    get_resp = _ok_response(200)
    with (
        patch("pipeline.verify.requests.head", return_value=head_resp),
        patch("pipeline.verify.requests.get", return_value=get_resp),
    ):
        check_link("https://example.com/head-not-allowed")
    get_resp.close.assert_called_once()


def test_check_link_rejects_private_host():
    with patch("pipeline.verify.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 0))]):
        ok, detail = check_link("http://10.0.0.1/internal")
    assert ok is False
    assert "unsafe" in detail


def test_check_link_rejects_bad_scheme():
    ok, detail = check_link("javascript:alert(1)")
    assert ok is False
    assert "scheme" in detail


def test_fuzzy_contains_true_for_real_substring():
    excerpt = "Enterprise customers can now request our SOC 2 Type II report directly."
    claim = "customers can now request our SOC 2 Type II report"
    assert _fuzzy_contains(claim, excerpt) is True


def test_fuzzy_contains_false_for_fabricated_claim():
    excerpt = "A small team released an open-source plugin that adds inline suggestions."
    claim = "the plugin reached 50,000 downloads in its first week"
    assert _fuzzy_contains(claim, excerpt) is False


@patch("pipeline.verify.check_link", return_value=(True, "HTTP 200"))
def test_verify_entry_clear_when_everything_checks_out(_mock_link):
    entry = {
        "cluster_id": "c1",
        "title": "Real story",
        "url": "https://example.com/a",
        "franchise": "weekly",
        "claims": [
            {
                "text": "vendor added SOC 2 Type II",
                "supported_by": "the vendor announced a new SOC 2 Type II report available on request",
            }
        ],
    }
    result = verify_entry(entry, RANKED)
    assert result["status"] == "clear"


@patch("pipeline.verify.check_link", return_value=(True, "HTTP 200"))
def test_verify_entry_flags_fabricated_claim(_mock_link):
    entry = {
        "cluster_id": "c1",
        "title": "Real story",
        "url": "https://example.com/a",
        "franchise": "weekly",
        "claims": [{"text": "x", "supported_by": "completely unrelated invented text"}],
    }
    result = verify_entry(entry, RANKED)
    assert result["status"] == "flagged"


@patch("pipeline.verify.check_link", return_value=(False, "HTTP 404"))
def test_verify_entry_blocks_on_dead_link(_mock_link):
    entry = {"cluster_id": "c1", "title": "Real story", "url": "https://example.com/a", "claims": []}
    result = verify_entry(entry, RANKED)
    assert result["status"] == "blocked"
    assert any("url failed" in r for r in result["reasons"])


@patch("pipeline.verify.check_link", return_value=(True, "HTTP 200"))
def test_verify_entry_blocks_on_invented_citation(_mock_link):
    entry = {"cluster_id": "does-not-exist", "title": "Fake", "url": "https://example.com/a", "claims": []}
    result = verify_entry(entry, RANKED)
    assert result["status"] == "blocked"
    assert any("not found" in r for r in result["reasons"])


@patch("pipeline.verify.check_link", return_value=(True, "HTTP 200"))
def test_vendor_watch_requires_primary_source(_mock_link):
    entry = {
        "cluster_id": "c1",
        "title": "Real story",
        "url": "https://example.com/a",
        "franchise": "vendor_watch",
        "claims": [],
    }
    result = verify_entry(entry, RANKED)
    assert result["status"] == "blocked"
    assert any("primary_source_url" in r for r in result["reasons"])


@patch("pipeline.verify.check_link", return_value=(True, "HTTP 200"))
def test_vendor_watch_passes_with_valid_primary_source(_mock_link):
    entry = {
        "cluster_id": "c1",
        "title": "Real story",
        "url": "https://example.com/a",
        "franchise": "vendor_watch",
        "primary_source_url": "https://vendor.example.com/changelog",
        "claims": [],
    }
    result = verify_entry(entry, RANKED)
    assert result["status"] == "clear"


@patch("pipeline.verify.check_link", return_value=(True, "HTTP 200"))
def test_verify_entry_flags_claim_whose_text_diverges_from_its_own_quote(_mock_link):
    # supported_by is a real, verbatim excerpt quote — but the claim's own
    # `text` asserts something the excerpt never said. Prior to the fix,
    # only supported_by was checked against the excerpt, so this passed as
    # `clear`; text must now be grounded too.
    entry = {
        "cluster_id": "c1",
        "title": "Real story",
        "url": "https://example.com/a",
        "franchise": "weekly",
        "claims": [
            {
                "text": "the vendor was fined $2 million by regulators for a data breach",
                "supported_by": "the vendor announced a new SOC 2 Type II report available on request",
            }
        ],
    }
    result = verify_entry(entry, RANKED)
    assert result["status"] == "flagged"
    assert any("unsupported claims" in r for r in result["reasons"])


@patch("pipeline.verify.check_link", return_value=(True, "HTTP 200"))
def test_verify_entry_flags_single_digit_altered_quote(_mock_link):
    # supported_by is character-for-character nearly identical to the real
    # excerpt (single digit swapped) — whole-string difflib similarity is
    # ~0.98 here, easily clearing the old 0.5 threshold. The numeric-token
    # check must catch this even though the raised fuzzy threshold alone
    # would not.
    entry = {
        "cluster_id": "c1",
        "title": "Real story",
        "url": "https://example.com/a",
        "franchise": "weekly",
        "claims": [
            {
                "text": "vendor added SOC 8 Type II",
                "supported_by": "the vendor announced a new SOC 8 Type II report available on request",
            }
        ],
    }
    result = verify_entry(entry, RANKED)
    assert result["status"] == "flagged"
    assert any("unsupported claims" in r for r in result["reasons"])


@patch("pipeline.verify.check_link", return_value=(True, "HTTP 200"))
def test_verify_entry_blocks_when_url_does_not_match_cited_cluster(_mock_link):
    # cluster_id is real (passes the citation-exists check) and claims are
    # properly grounded, but title/url point at a different story than the
    # one actually cited — the claims would only ever be checked against
    # the cited cluster's excerpt, so this must be caught independently.
    entry = {
        "cluster_id": "c1",
        "title": "A completely different story",
        "url": "https://example.com/different-story",
        "franchise": "weekly",
        "claims": [
            {
                "text": "vendor added SOC 2 Type II",
                "supported_by": "the vendor announced a new SOC 2 Type II report available on request",
            }
        ],
    }
    result = verify_entry(entry, RANKED)
    assert result["status"] == "blocked"
    assert any("does not match cited cluster_id" in r for r in result["reasons"])


def test_weekly_franchise_primary_source_url_is_still_link_checked():
    # §13.1 requires link resolution for "every url and primary_source_url
    # in the draft" — not just the two franchises that additionally
    # *require* one (§13.4). A non-vendor_watch/policy_corner entry that
    # includes a primary_source_url must still have it checked.
    entry = {
        "cluster_id": "c1",
        "title": "Real story",
        "url": "https://example.com/a",
        "franchise": "weekly",
        "primary_source_url": "https://example.com/dead-primary",
        "claims": [],
    }
    with patch(
        "pipeline.verify.check_link",
        side_effect=lambda url, session=None: (False, "HTTP 404") if "dead-primary" in url else (True, "HTTP 200"),
    ):
        result = verify_entry(entry, RANKED)
    assert result["status"] == "blocked"
    assert any("primary_source_url failed" in r for r in result["reasons"])


@patch("pipeline.verify.check_link", return_value=(False, "HTTP 404"))
def test_approved_override_downgrades_block_to_flagged(_mock_link):
    entry = {
        "cluster_id": "c1",
        "title": "Real story",
        "url": "https://example.com/a",
        "claims": [],
        "approved": True,
        "approved_reason": "checked manually, link works in a browser",
    }
    result = verify_entry(entry, RANKED)
    assert result["status"] == "flagged"
