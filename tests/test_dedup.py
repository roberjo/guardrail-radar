"""Tests for pipeline.dedup — see docs/technical-spec.md §9, §18."""

from pipeline.dedup import cluster_items


def _item(id_, title, source="hn", excerpt_status="none", excerpt=""):
    return {
        "id": id_,
        "title": title,
        "source": source,
        "url": f"https://example.com/{id_}",
        "excerpt_status": excerpt_status,
        "excerpt": excerpt,
    }


def test_near_duplicate_titles_cluster_together():
    items = [
        _item("a", "Claude Code ships a new agent SDK for enterprise teams"),
        _item("b", "Claude Code ships a new agent SDK for enterprise teams!", source="reddit"),
    ]
    clustered = cluster_items(items)
    assert clustered[0]["cluster_id"] == clustered[1]["cluster_id"]
    assert set(clustered[0]["cluster_sources"]) == {"hn", "reddit"}


def test_distinct_stories_do_not_over_merge():
    items = [
        _item("a", "Bank rolls out Copilot under a new compliance policy"),
        _item("b", "Startup raises seed round for an unrelated fintech product"),
    ]
    clustered = cluster_items(items)
    assert clustered[0]["cluster_id"] != clustered[1]["cluster_id"]


def test_token_overlap_catches_reordered_titles():
    items = [
        _item("a", "audit trails compliance vendor risk fintech copilot rollout"),
        _item("b", "copilot rollout fintech vendor risk compliance audit trails"),
    ]
    clustered = cluster_items(items)
    assert clustered[0]["cluster_id"] == clustered[1]["cluster_id"]


def test_best_excerpt_status_wins_as_cluster_representative():
    items = [
        _item("a", "Same story here", excerpt_status="none", excerpt=""),
        _item("b", "Same story here!", excerpt_status="ok", excerpt="the real excerpt text"),
        _item("c", "Same story here.", excerpt_status="partial", excerpt="a fallback excerpt"),
    ]
    clustered = cluster_items(items)
    cluster_excerpts = {c["cluster_excerpt"] for c in clustered}
    assert cluster_excerpts == {"the real excerpt text"}
    assert all(c["cluster_excerpt_status"] == "ok" for c in clustered)


def test_empty_input_returns_empty_list():
    assert cluster_items([]) == []


def test_skips_malformed_item_without_crashing_whole_batch(capsys):
    good_a = _item("a", "Bank rolls out Copilot under a new compliance policy")
    good_c = _item("c", "Startup raises seed round for an unrelated fintech product")
    malformed = {"id": "bad", "source": "hn", "url": "https://example.com/bad"}  # missing title

    clustered = cluster_items([good_a, malformed, good_c])

    assert {c["id"] for c in clustered} == {"a", "c"}
    captured = capsys.readouterr()
    assert "skipping malformed item" in captured.err
