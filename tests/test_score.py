"""Tests for pipeline.score — see docs/technical-spec.md §10, §18."""

from datetime import datetime, timezone

from pipeline.score import compute_item_score, score_items

NOW = datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc)  # 24h after posted_at below
POSTED_AT = "2026-01-01T00:00:00Z"


def test_velocity_score_is_raw_score_over_hours():
    item = {"posted_at": POSTED_AT, "raw_score": 48, "comment_count": 0}
    velocity, _ = compute_item_score(item, NOW)
    assert velocity == 2.0  # 48 points / 24 hours


def test_discussion_ratio_boosts_item_score_but_caps_at_1():
    no_discussion = {"posted_at": POSTED_AT, "raw_score": 10, "comment_count": 0}
    some_discussion = {"posted_at": POSTED_AT, "raw_score": 10, "comment_count": 10}
    lots_of_discussion = {"posted_at": POSTED_AT, "raw_score": 10, "comment_count": 100}

    _, base = compute_item_score(no_discussion, NOW)
    _, boosted = compute_item_score(some_discussion, NOW)
    _, capped = compute_item_score(lots_of_discussion, NOW)

    assert boosted == base * 2  # discussion_ratio == 1.0
    assert capped == boosted  # min(discussion_ratio, 1.0) caps further boost


def test_hours_since_post_floors_at_one_hour():
    just_posted = {"posted_at": NOW.isoformat(), "raw_score": 10, "comment_count": 0}
    velocity, _ = compute_item_score(just_posted, NOW)
    assert velocity == 10.0  # not division by ~0


def test_cross_source_bonus_multiplies_cluster_score():
    single_source = [
        {"id": "a", "cluster_id": "c1", "source": "hn", "posted_at": POSTED_AT, "raw_score": 10, "comment_count": 0},
    ]
    two_sources = [
        {"id": "b", "cluster_id": "c2", "source": "hn", "posted_at": POSTED_AT, "raw_score": 10, "comment_count": 0},
        {"id": "c", "cluster_id": "c2", "source": "reddit", "posted_at": POSTED_AT, "raw_score": 1, "comment_count": 0},
    ]
    scored_single = score_items(single_source, now=NOW)
    scored_multi = score_items(two_sources, now=NOW)

    single_cluster_score = scored_single[0]["cluster_score"]
    multi_cluster_score = scored_multi[0]["cluster_score"]
    max_item_score = max(i["item_score"] for i in scored_multi)

    assert multi_cluster_score == max_item_score * 1.25
    # Same underlying item_score magnitude, but the two-source cluster wins.
    assert multi_cluster_score > single_cluster_score


def test_cluster_score_uses_max_item_score_in_cluster():
    items = [
        {"id": "a", "cluster_id": "c1", "source": "hn", "posted_at": POSTED_AT, "raw_score": 5, "comment_count": 0},
        {"id": "b", "cluster_id": "c1", "source": "hn", "posted_at": POSTED_AT, "raw_score": 50, "comment_count": 0},
    ]
    scored = score_items(items, now=NOW)
    expected = max(i["item_score"] for i in scored)
    assert all(i["cluster_score"] == expected for i in scored)


def test_skips_malformed_item_without_crashing_whole_batch(capsys):
    good = {"id": "a", "cluster_id": "c1", "source": "hn", "posted_at": POSTED_AT, "raw_score": 10, "comment_count": 0}
    missing_posted_at = {"id": "b", "cluster_id": "c1", "source": "hn", "raw_score": 10, "comment_count": 0}
    garbage_posted_at = {
        "id": "c", "cluster_id": "c1", "source": "hn",
        "posted_at": "not-a-date", "raw_score": 10, "comment_count": 0,
    }

    scored = score_items([good, missing_posted_at, garbage_posted_at], now=NOW)

    assert [i["id"] for i in scored] == ["a"]
    captured = capsys.readouterr()
    assert captured.err.count("skipping malformed item") == 2
