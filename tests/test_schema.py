"""Tests for pipeline.schema — see docs/technical-spec.md §5."""

import pytest

from pipeline.schema import NormalizedItem, canonicalize_url, item_id


def test_canonicalize_strips_tracking_params():
    url = "https://Example.com/Post?utm_source=hn&id=42&ref=abc"
    assert canonicalize_url(url) == "https://example.com/Post?id=42"


def test_canonicalize_lowercases_host_only():
    url = "https://EXAMPLE.com/Some/Path"
    assert canonicalize_url(url) == "https://example.com/Some/Path"


def test_canonicalize_strips_trailing_slash():
    assert canonicalize_url("https://example.com/path/") == "https://example.com/path"
    assert canonicalize_url("https://example.com") == "https://example.com/"


def test_item_id_is_deterministic():
    url = "https://example.com/a"
    assert item_id(url) == item_id(url)
    assert item_id(url) != item_id("https://example.com/b")


def test_normalized_item_computes_id_from_canonical_url():
    item = NormalizedItem(
        source="hn",
        title="Example",
        url="https://Example.com/x?utm_source=hn",
        raw_score=10,
        comment_count=2,
        posted_at="2026-01-01T00:00:00Z",
        fetched_at="2026-01-01T01:00:00Z",
    )
    assert item.url == "https://example.com/x"
    assert item.id == item_id("https://example.com/x")


def test_normalized_item_rejects_unknown_source():
    with pytest.raises(ValueError):
        NormalizedItem(
            source="twitter",
            title="x",
            url="https://example.com",
            raw_score=0,
            comment_count=0,
            posted_at="2026-01-01T00:00:00Z",
            fetched_at="2026-01-01T00:00:00Z",
        )


def test_normalized_item_rejects_invalid_excerpt_status():
    with pytest.raises(ValueError):
        NormalizedItem(
            source="hn",
            title="x",
            url="https://example.com",
            raw_score=0,
            comment_count=0,
            posted_at="2026-01-01T00:00:00Z",
            fetched_at="2026-01-01T00:00:00Z",
            excerpt_status="maybe",
        )


def test_round_trip_to_dict_from_dict():
    item = NormalizedItem(
        source="lobsters",
        title="x",
        url="https://example.com/a",
        raw_score=1,
        comment_count=1,
        posted_at="2026-01-01T00:00:00Z",
        fetched_at="2026-01-01T00:00:00Z",
        source_meta={"short_id": "abc"},
    )
    restored = NormalizedItem.from_dict(item.to_dict())
    assert restored == item
