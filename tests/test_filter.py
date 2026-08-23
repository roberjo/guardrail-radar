"""Tests for pipeline.filter — see docs/technical-spec.md §11, §18."""

from datetime import datetime, timezone

from pipeline.filter import _velocity_threshold, filter_and_rank, passes_filter
from pipeline.score import score_items

CORE = ["copilot", "claude code", "cursor"]
CONTEXT = ["compliance", "fintech", "audit"]
NOW = datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
POSTED_AT = "2026-01-01T00:00:00Z"


def test_passes_with_one_term_from_each_set():
    item = {"title": "Bank adopts Copilot under new compliance rules", "excerpt": ""}
    assert passes_filter(item, CORE, CONTEXT, velocity_threshold=999) is True


def test_fails_with_only_core_terms_and_low_velocity():
    item = {"title": "Copilot gets a new autocomplete mode", "excerpt": "", "velocity_score": 0.1}
    assert passes_filter(item, CORE, CONTEXT, velocity_threshold=1.0) is False


def test_passes_with_one_core_term_and_high_velocity():
    # Loosened from a 2-core-terms requirement after real data showed the
    # AND-with-context rule passed zero HN/GitHub items — see
    # CHANGELOG.md. A single core term plus real engagement is now enough.
    item = {
        "title": "Copilot gets a new autocomplete mode",
        "excerpt": "",
        "velocity_score": 5.0,
    }
    assert passes_filter(item, CORE, CONTEXT, velocity_threshold=1.0) is True


def test_fails_with_no_matching_terms_at_all():
    item = {"title": "A completely unrelated story about gardening", "excerpt": ""}
    assert passes_filter(item, CORE, CONTEXT, velocity_threshold=0) is False


def test_matches_terms_in_excerpt_not_just_title():
    item = {
        "title": "New tool released",
        "excerpt": "built for teams that need to pass a SOX audit before shipping",
        "velocity_score": 0,
    }
    # "audit" (context) present, but needs a core term too.
    assert passes_filter(item, CORE, CONTEXT, velocity_threshold=999) is False
    item["excerpt"] += " using claude code"
    assert passes_filter(item, CORE, CONTEXT, velocity_threshold=999) is True


def test_velocity_threshold_defaults_to_top_quartile():
    items = [{"velocity_score": v} for v in [10, 8, 6, 4, 2, 0, 0, 0]]
    # top 25% of 8 items = 2 items -> cutoff is the 2nd-highest score
    assert _velocity_threshold(items) == 8


def test_filter_and_rank_picks_best_scoring_item_per_cluster(monkeypatch):
    # cluster_score is uniform within a cluster in real pipeline.score
    # output — item_score is the field that actually varies per item and
    # must drive which item represents the cluster.
    monkeypatch.setattr(
        "pipeline.filter._load_keywords", lambda path="config/keywords.yml": (CORE, CONTEXT)
    )
    items = [
        {
            "cluster_id": "c1",
            "title": "Copilot rollout passes a bank's compliance review",
            "excerpt": "",
            "velocity_score": 1.0,
            "item_score": 2.0,
            "cluster_score": 5.0,
        },
        {
            "cluster_id": "c1",
            "title": "Copilot rollout passes a bank's compliance review (duplicate)",
            "excerpt": "",
            "velocity_score": 1.0,
            "item_score": 9.0,
            "cluster_score": 5.0,
        },
        {
            "cluster_id": "c2",
            "title": "Totally unrelated gardening post",
            "excerpt": "",
            "velocity_score": 0,
            "item_score": 100.0,
            "cluster_score": 100.0,
        },
    ]
    ranked = filter_and_rank(items)
    assert len(ranked) == 1
    assert ranked[0]["cluster_id"] == "c1"
    assert ranked[0]["item_score"] == 9.0
    assert ranked[0]["cluster_score"] == 5.0


def test_filter_and_rank_representative_picked_by_engagement_not_source_alphabetical_order(monkeypatch):
    # Regression test for the bug where every item in a cluster shares one
    # uniform cluster_score, so filter.py's old `>` comparison on
    # cluster_score never fired and the first item in iteration order (glob
    # order: github < reddit) silently won regardless of actual engagement.
    # Route real pipeline.score output through filter_and_rank so the
    # per-item item_score values are the genuine ones score.py produces,
    # not hand-set test fixtures.
    monkeypatch.setattr(
        "pipeline.filter._load_keywords", lambda path="config/keywords.yml": (CORE, CONTEXT)
    )
    raw_items = [
        {
            "id": "g1",
            "cluster_id": "c1",
            "source": "github",
            "title": "Copilot rollout passes a bank's compliance review",
            "url": "https://example.com/github-item",
            "excerpt": "",
            "posted_at": POSTED_AT,
            "raw_score": 1,
            "comment_count": 0,
        },
        {
            "id": "r1",
            "cluster_id": "c1",
            "source": "reddit",
            "title": "Copilot rollout passes a bank's compliance review, discussion",
            "url": "https://example.com/reddit-item",
            "excerpt": "",
            "posted_at": POSTED_AT,
            "raw_score": 500,
            "comment_count": 500,
        },
    ]
    scored = score_items(raw_items, now=NOW)
    # Confirm the premise: cluster_score is uniform, item_score is not.
    assert scored[0]["cluster_score"] == scored[1]["cluster_score"]
    assert scored[0]["item_score"] != scored[1]["item_score"]

    ranked = filter_and_rank(scored)
    assert len(ranked) == 1
    assert ranked[0]["source"] == "reddit"


def test_filter_and_rank_respects_top_n(monkeypatch):
    monkeypatch.setattr(
        "pipeline.filter._load_keywords", lambda path="config/keywords.yml": (CORE, CONTEXT)
    )
    items = [
        {
            "cluster_id": f"c{i}",
            "title": f"Copilot compliance story number {i}",
            "excerpt": "",
            "velocity_score": 1.0,
            "cluster_score": float(i),
        }
        for i in range(40)
    ]
    ranked = filter_and_rank(items)
    assert len(ranked) == 30
    assert ranked[0]["cluster_score"] == 39.0
