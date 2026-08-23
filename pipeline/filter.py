"""Relevance filtering — see docs/technical-spec.md §11.

Reads data/interim/<iso-week>.json (dedup'd + scored), picks the
best-scoring passing item per cluster, ranks the top 30, and writes
data/ranked/<iso-week>.json.
"""

from __future__ import annotations

import os

import yaml

from pipeline.io_utils import iso_week_str, read_json, write_json

TOP_N = 30


def _load_keywords(path: str = "config/keywords.yml") -> tuple[list[str], list[str]]:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg.get("core_terms", []), cfg.get("context_terms", [])


def _text(item: dict) -> str:
    return f"{item.get('title', '')} {item.get('excerpt', '')}".lower()


def _velocity_threshold(items: list[dict], percentile: float = 0.25) -> float:
    """velocity_score cutoff for the top `percentile` fraction of the week's items (§11).

    Was a fixed top-decile (0.1) gating a 2+-core-terms bypass. Found live,
    against a real 345-item single-day pull (see CHANGELOG.md): the
    core+context AND-requirement below is a poor fit for how HN/GitHub
    titles are actually phrased — 49/111 HN items mentioned an AI-coding
    term, 0 also mentioned a fintech/compliance term in the same
    title+excerpt text, so literally nothing outside Product Hunt could
    ever pass. Loosened to top-quartile (0.25) so a single core-term hit
    with real engagement is enough on its own — the human curator in
    draft-digest still decides what actually ships, so a broader ranked
    pool here is a curation-material problem, not a hallucination risk.
    """
    scores = sorted((it.get("velocity_score", 0) for it in items), reverse=True)
    if not scores:
        return float("inf")
    cutoff_index = max(0, int(len(scores) * percentile) - 1)
    return scores[cutoff_index]


def passes_filter(
    item: dict, core_terms: list[str], context_terms: list[str], velocity_threshold: float
) -> bool:
    text = _text(item)
    core_hits = [t for t in core_terms if t.lower() in text]
    context_hits = [t for t in context_terms if t.lower() in text]

    if core_hits and context_hits:
        return True
    return bool(core_hits and item.get("velocity_score", 0) >= velocity_threshold)


def filter_and_rank(items: list[dict]) -> list[dict]:
    core_terms, context_terms = _load_keywords()
    threshold = _velocity_threshold(items)

    passing = [it for it in items if passes_filter(it, core_terms, context_terms, threshold)]

    # cluster_score is uniform across every item in a cluster (see
    # pipeline.score) — it's the right key for the final ranking sort below,
    # but useless for choosing *which* item represents the cluster. Use
    # item_score (per-item, varies within a cluster) for that instead,
    # otherwise the first item in iteration order silently wins (see
    # CHANGELOG.md / prior bug).
    best_per_cluster: dict[str, dict] = {}
    for item in passing:
        cid = item["cluster_id"]
        if cid not in best_per_cluster or item["item_score"] > best_per_cluster[cid]["item_score"]:
            best_per_cluster[cid] = item

    ranked = sorted(best_per_cluster.values(), key=lambda it: it["cluster_score"], reverse=True)
    return ranked[:TOP_N]


def main() -> None:
    iso_week = iso_week_str()
    interim_path = os.path.join("data", "interim", f"{iso_week}.json")
    items = read_json(interim_path)
    ranked = filter_and_rank(items)

    # Normalize each ranked entry to just the fields render/verify need —
    # keeps data/ranked lean and stable rather than dragging along every
    # scoring intermediate.
    out = [
        {
            "cluster_id": it["cluster_id"],
            "title": it["title"],
            "url": it["url"],
            "source": it["source"],
            "cluster_sources": it.get("cluster_sources", [it["source"]]),
            "cluster_score": it["cluster_score"],
            "cluster_excerpt": it.get("cluster_excerpt", ""),
            "excerpt_status": it.get("cluster_excerpt_status", it.get("excerpt_status", "none")),
        }
        for it in ranked
    ]

    out_path = os.path.join("data", "ranked", f"{iso_week}.json")
    write_json(out_path, out)
    print(f"[filter] {len(items)} scored items -> {len(out)} ranked clusters -> {out_path}")


if __name__ == "__main__":
    main()
