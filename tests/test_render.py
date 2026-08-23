"""Tests for pipeline.render — see docs/technical-spec.md §14, §18.

Runs entirely against a temp working directory (monkeypatch.chdir) so the
module's relative data/digest/site paths are isolated per test. Includes a
regression test for the site-archive duplication/corruption bug found by
the reviewer agent and fixed twice (the first fix looked right but still
corrupted the HTML on a second render) — see CHANGELOG.md.
"""

import json
import os

import pytest

from pipeline.render import (
    _issue_stats_line,
    _read_time_minutes,
    render_final_digest,
    render_review_packet,
)

PLACEHOLDER_SITE_HTML = """<!doctype html>
<html><body>
<div class="archive">
  <ul>
    <!-- pipeline/render.py appends one <li> per published week here, per docs/technical-spec.md §14 -->
  </ul>
  <p class="empty">First issue coming soon.</p>
</div>
</body></html>
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for d in ("data/ranked", "digest/draft", "digest/verification", "digest/review", "site"):
        os.makedirs(d, exist_ok=True)
    with open("site/index.html", "w", encoding="utf-8") as f:
        f.write(PLACEHOLDER_SITE_HTML)
    return tmp_path


def _write(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _write_draft(path: str, items: list, intro: str = "") -> None:
    """digest/draft/<week>.json is {"intro": ..., "items": [...]} — see
    docs/technical-spec.md §12.2. intro is optional connective narrative
    for the whole issue, added after real user feedback that isolated
    per-item summaries with no frame read as a link list, not a newsletter.
    """
    _write(path, {"intro": intro, "items": items})


def _ranked_cluster(cluster_id="c1", title="A real story", excerpt="a real excerpt", status="ok"):
    return {
        "cluster_id": cluster_id,
        "title": title,
        "url": "https://example.com/story",
        "source": "hn",
        "cluster_sources": ["hn"],
        "cluster_score": 4.2,
        "cluster_excerpt": excerpt,
        "excerpt_status": status,
    }


def _draft_entry(cluster_id="c1", franchise="weekly", **overrides):
    entry = {
        "cluster_id": cluster_id,
        "title": "A real story",
        "url": "https://example.com/story",
        "franchise": franchise,
        "category": "new_product",
        "hook": "Why it's worth a look at all.",
        "note": "Why this matters to a compliance-constrained engineer.",
        "claims": [],
    }
    entry.update(overrides)
    return entry


# ---------- review packet ----------


def test_review_packet_includes_score_and_excerpt(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    content = render_review_packet("2026-W01")
    assert "A real story" in content
    assert "a real excerpt" in content
    assert "4.20" in content
    assert "c1" in content


def test_review_packet_flags_insufficient_source_text(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster(excerpt="", status="none")])
    content = render_review_packet("2026-W01")
    assert "insufficient source text" in content


def test_review_packet_escapes_markdown_special_chars_in_title(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster(title="A [fake] *link* here")])
    content = render_review_packet("2026-W01")
    assert "\\[fake\\]" in content
    assert "\\*link\\*" in content


def test_review_packet_escapes_unbalanced_paren_in_url(project):
    cluster = _ranked_cluster()
    cluster["url"] = "https://example.com/wiki/Foo_(bar)"
    _write("data/ranked/2026-W01.json", [cluster])
    content = render_review_packet("2026-W01")
    assert "https://example.com/wiki/Foo_(bar%29" in content
    assert "](https://example.com/wiki/Foo_(bar)" not in content


# ---------- final digest: content ----------


def test_final_digest_renders_note_and_excerpt(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry()])
    digest_path, _site_path = render_final_digest("2026-W01")
    with open(digest_path, encoding="utf-8") as f:
        content = f.read()
    assert "Why this matters to a compliance-constrained engineer." in content
    assert "a real excerpt" in content


def test_final_digest_renders_intro_in_digest_and_site(project):
    # Added after real user feedback: three isolated per-item summaries
    # with no frame or synthesis read as a bare link list, not a
    # newsletter. intro is optional connective narrative for the whole
    # issue — see docs/technical-spec.md §12.2.
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry()],
        intro="A dry, professional aside that ties the week together.",
    )
    digest_path, site_path = render_final_digest("2026-W01")
    with open(digest_path, encoding="utf-8") as f:
        digest_content = f.read()
    with open(site_path, encoding="utf-8") as f:
        site_content = f.read()
    assert "A dry, professional aside that ties the week together." in digest_content
    assert "A dry, professional aside that ties the week together." in site_content
    assert 'class="issue-intro"' in site_content


def test_final_digest_omits_intro_block_when_not_provided(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry()])  # no intro
    _, site_path = render_final_digest("2026-W01")
    with open(site_path, encoding="utf-8") as f:
        site_content = f.read()
    assert "issue-intro" not in site_content


def test_final_digest_escapes_intro_html(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft(
        "digest/draft/2026-W01.json", [_draft_entry()], intro='<script>alert(3)</script>'
    )
    _, site_path = render_final_digest("2026-W01")
    with open(site_path, encoding="utf-8") as f:
        site_content = f.read()
    assert "<script>alert(3)</script>" not in site_content


def test_final_digest_renders_hook_before_excerpt_and_note(project):
    # Added after real user feedback: readers need a one-sentence,
    # plain-English reason an item is worth their time, front-running the
    # item, before the longer skeptical note — see docs/technical-spec.md
    # §12.2.
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(hook="Proves the agent fix actually held, not just that it passed CI.")],
    )
    digest_path, site_path = render_final_digest("2026-W01")
    with open(digest_path, encoding="utf-8") as f:
        digest_content = f.read()
    with open(site_path, encoding="utf-8") as f:
        site_content = f.read()

    hook_text = "Proves the agent fix actually held, not just that it passed CI."
    assert hook_text in digest_content
    assert digest_content.index(hook_text) < digest_content.index("a real excerpt")
    assert 'class="item-hook new_product"' in site_content  # default category from _draft_entry
    assert hook_text in site_content
    assert site_content.index(hook_text) < site_content.index("a real excerpt")


def test_final_digest_omits_hook_block_when_not_provided(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(hook="")])
    _, site_path = render_final_digest("2026-W01")
    with open(site_path, encoding="utf-8") as f:
        site_content = f.read()
    assert "item-hook" not in site_content


def test_final_digest_escapes_hook_html(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft(
        "digest/draft/2026-W01.json", [_draft_entry(hook='<script>alert(4)</script>')]
    )
    _, site_path = render_final_digest("2026-W01")
    with open(site_path, encoding="utf-8") as f:
        site_content = f.read()
    assert "<script>alert(4)</script>" not in site_content
    assert "&lt;script&gt;" in site_content


def test_final_digest_toc_groups_by_category_in_fixed_order(project):
    # Added after a direct user request for a table of contents grouped by
    # area/criticality — see docs/technical-spec.md §12.2. CATEGORY_ORDER
    # is breaking, new_product, notable, field_notes regardless of input
    # order, and a category absent from the draft is omitted entirely.
    _write(
        "data/ranked/2026-W01.json",
        [
            _ranked_cluster(cluster_id="c1", title="A notable one"),
            _ranked_cluster(cluster_id="c2", title="A breaking one"),
            _ranked_cluster(cluster_id="c3", title="A new product one"),
        ],
    )
    _write_draft(
        "digest/draft/2026-W01.json",
        [
            _draft_entry(cluster_id="c1", title="A notable one", category="notable"),
            _draft_entry(cluster_id="c2", title="A breaking one", category="breaking"),
            _draft_entry(cluster_id="c3", title="A new product one", category="new_product"),
        ],
    )
    digest_path, site_path = render_final_digest("2026-W01")
    with open(digest_path, encoding="utf-8") as f:
        digest_content = f.read()
    with open(site_path, encoding="utf-8") as f:
        site_content = f.read()

    # Fixed order: Breaking News, then New Products & Tools, then Notable.
    # site_content has "&" html-escaped to "&amp;" in the category label.
    assert digest_content.index("Breaking News") < digest_content.index("New Products & Tools")
    assert digest_content.index("New Products & Tools") < digest_content.index("Notable / Wow")
    assert site_content.index("Breaking News") < site_content.index("New Products &amp; Tools")
    assert site_content.index("New Products &amp; Tools") < site_content.index("Notable / Wow")

    # A category with no items (field_notes here) isn't shown at all.
    assert "Field Notes" not in digest_content
    assert "Field Notes" not in site_content

    assert 'class="toc"' in site_content
    assert '<a href="#item-c2">A breaking one</a>' in site_content


def test_final_digest_toc_anchor_matches_item_id(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster(cluster_id="c1", title="A real story")])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(cluster_id="c1")])
    _, site_path = render_final_digest("2026-W01")
    with open(site_path, encoding="utf-8") as f:
        site_content = f.read()
    assert 'href="#item-c1"' in site_content
    assert 'id="item-c1"' in site_content


def test_read_time_minutes_rounds_and_has_a_floor():
    # Added after a format audit against comparable newsletters (TLDR, The
    # Batch) that all surface a read-time signal — pure text-derived, no
    # new drafted field. WORDS_PER_MINUTE = 200.
    assert _read_time_minutes("word " * 10) == 1  # floor: never 0, even for a handful of words
    assert _read_time_minutes("word " * 200) == 1  # exactly 1 minute's worth
    assert _read_time_minutes("word " * 450) == 2  # round(450/200) == round(2.25) == 2
    assert _read_time_minutes("word " * 250, "word " * 200) == 2  # summed across multiple text args (450 total)


def test_final_digest_shows_category_badge_and_read_time(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(category="notable")])
    digest_path, site_path = render_final_digest("2026-W01")
    with open(digest_path, encoding="utf-8") as f:
        digest_content = f.read()
    with open(site_path, encoding="utf-8") as f:
        site_content = f.read()

    assert "`Notable` ·" in digest_content
    assert "min read" in digest_content
    assert 'class="category-badge notable"><span class="dot"></span>Notable</span>' in site_content
    assert 'class="read-time">' in site_content and "min read" in site_content


def test_final_digest_each_category_gets_its_own_badge_and_hook_class(project):
    # Follow-up to real feedback that at-a-glance scanning needed more
    # than "breaking vs. everything else" — all 4 categories now get
    # distinct colors (via CSS classes), not just breaking.
    for i, category in enumerate(["breaking", "new_product", "notable", "field_notes"]):
        cid = f"c{i}"
        _write("data/ranked/2026-W01.json", [_ranked_cluster(cluster_id=cid)])
        _write_draft("digest/draft/2026-W01.json", [_draft_entry(cluster_id=cid, category=category)])
        _, site_path = render_final_digest("2026-W01")
        with open(site_path, encoding="utf-8") as f:
            site_content = f.read()
        assert f'class="category-badge {category}">' in site_content
        assert f'class="item-hook {category}"' in site_content
        assert f'class="issue-item {category}"' in site_content


def test_final_digest_toc_group_shows_item_count(project):
    _write(
        "data/ranked/2026-W01.json",
        [_ranked_cluster(cluster_id="c1"), _ranked_cluster(cluster_id="c2", title="Second story")],
    )
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(cluster_id="c1", category="breaking"), _draft_entry(cluster_id="c2", category="breaking")],
    )
    digest_path, site_path = render_final_digest("2026-W01")
    with open(digest_path, encoding="utf-8") as f:
        digest_content = f.read()
    with open(site_path, encoding="utf-8") as f:
        site_content = f.read()
    assert "Breaking News (2)" in digest_content
    assert 'class="toc-group breaking"' in site_content
    assert '<span class="count">(2)</span>' in site_content


def test_final_digest_markdown_bolds_breaking_but_not_other_categories(project):
    # Plain markdown has no color, so BREAKING gets bold+uppercase instead —
    # the same "one category pops, the rest recede" rule the site's color
    # coding follows, translated to what markdown can actually do.
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(category="breaking")])
    digest_path, _ = render_final_digest("2026-W01")
    with open(digest_path, encoding="utf-8") as f:
        breaking_content = f.read()
    assert "**BREAKING** ·" in breaking_content
    assert "`Breaking`" not in breaking_content

    _write_draft("digest/draft/2026-W01.json", [_draft_entry(category="notable")])
    digest_path, _ = render_final_digest("2026-W01")
    with open(digest_path, encoding="utf-8") as f:
        notable_content = f.read()
    assert "`Notable` ·" in notable_content
    assert "**NOTABLE**" not in notable_content


def test_issue_stats_line_counts_items_sources_and_categories():
    draft = [
        {"cluster_id": "c1", "category": "breaking"},
        {"cluster_id": "c2", "category": "breaking"},
        {"cluster_id": "c3", "category": "new_product"},
    ]
    ranked_by_cluster = {
        "c1": {"cluster_sources": ["hn"]},
        "c2": {"cluster_sources": ["github"]},
        "c3": {"cluster_sources": ["hn", "producthunt"]},
    }
    line = _issue_stats_line(draft, ranked_by_cluster)
    assert line == "In this issue: 3 items across 3 sources — 2 breaking, 1 new product."


def test_final_digest_shows_issue_stats_line(project):
    _write(
        "data/ranked/2026-W01.json",
        [_ranked_cluster(cluster_id="c1"), _ranked_cluster(cluster_id="c2", title="Second story")],
    )
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(cluster_id="c1", category="breaking"), _draft_entry(cluster_id="c2", category="notable")],
    )
    digest_path, site_path = render_final_digest("2026-W01")
    with open(digest_path, encoding="utf-8") as f:
        digest_content = f.read()
    with open(site_path, encoding="utf-8") as f:
        site_content = f.read()
    assert "In this issue: 2 items across 1 source — 1 breaking, 1 notable." in digest_content
    assert 'class="issue-stats"' in site_content
    assert "In this issue: 2 items across 1 source" in site_content


def test_final_digest_excerpt_collapsed_on_site_not_in_markdown(project):
    # Site-only: <details> can't be relied on to survive a paste into
    # Substack/Beehiiv, so the emailed digest keeps the excerpt always
    # visible as a plain blockquote.
    _write("data/ranked/2026-W01.json", [_ranked_cluster(excerpt="a real excerpt")])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry()])
    digest_path, site_path = render_final_digest("2026-W01")
    with open(digest_path, encoding="utf-8") as f:
        digest_content = f.read()
    with open(site_path, encoding="utf-8") as f:
        site_content = f.read()
    assert "<details>" not in digest_content
    assert "> a real excerpt" in digest_content
    assert "<details><summary>Read the source excerpt</summary>" in site_content
    assert "a real excerpt" in site_content


def test_final_digest_shows_non_weekly_franchise_label(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(franchise="vendor_watch", primary_source_url="https://vendor.example.com/changelog")],
    )
    digest_path, _ = render_final_digest("2026-W01")
    with open(digest_path, encoding="utf-8") as f:
        content = f.read()
    assert "Vendor Watch" in content
    assert "Primary source: https://vendor.example.com/changelog" in content


def test_final_digest_escapes_primary_source_url(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(primary_source_url="https://vendor.example.com/*not*markdown*")],
    )
    digest_path, _ = render_final_digest("2026-W01")
    with open(digest_path, encoding="utf-8") as f:
        content = f.read()
    assert r"https://vendor.example.com/\*not\*markdown\*" in content


def test_final_digest_omits_link_when_no_http_url_available(project, capsys):
    cluster = _ranked_cluster()
    cluster["url"] = "javascript:alert(1)"
    _write("data/ranked/2026-W01.json", [cluster])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(url="javascript:alert(1)")])
    digest_path, site_path = render_final_digest("2026-W01")
    with open(digest_path, encoding="utf-8") as f:
        digest_content = f.read()
    with open(site_path, encoding="utf-8") as f:
        site_content = f.read()
    assert "javascript:" not in digest_content
    assert "javascript:" not in site_content
    assert "A real story" in digest_content
    # Scope to the actual issue-item, not the TOC above it — the TOC
    # legitimately contains its own <a href="#item-..."> anchor link to
    # this same item, which isn't the unsafe url this test is guarding
    # against.
    item_html = site_content.split('class="issue-items"')[1].split("</li>")[0]
    assert "<a href" not in item_html


def test_final_digest_refuses_when_blocked_and_unapproved(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry()])
    _write(
        "digest/verification/2026-W01.json",
        [{"cluster_id": "c1", "title": "A real story", "status": "blocked", "reasons": ["url failed"]}],
    )
    with pytest.raises(RuntimeError, match="unresolved blocked entries"):
        render_final_digest("2026-W01")
    assert not os.path.exists("digest/2026-W01.md")


def test_final_digest_proceeds_when_blocked_entry_is_approved(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(approved=True, approved_reason="checked by hand")])
    _write(
        "digest/verification/2026-W01.json",
        [{"cluster_id": "c1", "title": "A real story", "status": "blocked", "reasons": ["url failed"]}],
    )
    digest_path, _ = render_final_digest("2026-W01")
    assert os.path.exists(digest_path)


def test_final_digest_html_escapes_untrusted_title_and_url(project):
    malicious_title = '<script>alert(1)</script>'
    _write("data/ranked/2026-W01.json", [_ranked_cluster(title=malicious_title)])
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(title=malicious_title, url='https://example.com/"><script>x</script>')],
    )
    _, site_path = render_final_digest("2026-W01")
    with open(site_path, encoding="utf-8") as f:
        site_html = f.read()
    assert "<script>alert(1)</script>" not in site_html
    assert "&lt;script&gt;" in site_html


# ---------- site archive: full content (not just a bare title link) ----------


def test_site_archive_includes_excerpt_and_note_not_just_title(project):
    # Regression test: the site previously rendered only a bare
    # <li><a>title</a></li> per item — the actual commentary (note) and
    # excerpt went into digest/<week>.md but never reached site/index.html,
    # despite docs/technical-spec.md §14 saying the site gets "the same
    # content." Found by the user looking at the real deployed site, not
    # by a test — there wasn't one that checked this.
    _write("data/ranked/2026-W01.json", [_ranked_cluster(excerpt="a real excerpt")])
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(note="Why this matters to a compliance-constrained engineer.")],
    )
    _, site_path = render_final_digest("2026-W01")
    with open(site_path, encoding="utf-8") as f:
        site_html = f.read()
    assert "a real excerpt" in site_html
    assert "Why this matters to a compliance-constrained engineer." in site_html


def test_site_archive_shows_franchise_tag_and_primary_source(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(franchise="vendor_watch", primary_source_url="https://vendor.example.com/changelog")],
    )
    _, site_path = render_final_digest("2026-W01")
    with open(site_path, encoding="utf-8") as f:
        site_html = f.read()
    assert "Vendor Watch" in site_html
    assert 'href="https://vendor.example.com/changelog"' in site_html


def test_site_archive_omits_franchise_tag_for_plain_weekly_items(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(franchise="weekly")])
    _, site_path = render_final_digest("2026-W01")
    with open(site_path, encoding="utf-8") as f:
        site_html = f.read()
    assert "franchise-tag" not in site_html


def test_site_archive_escapes_note_and_excerpt_html(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster(excerpt='<img src=x onerror="alert(1)">')])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(note='<script>alert(2)</script>')])
    _, site_path = render_final_digest("2026-W01")
    with open(site_path, encoding="utf-8") as f:
        site_html = f.read()
    assert "<script>alert(2)</script>" not in site_html
    assert "<img src=x" not in site_html
    assert "&lt;script&gt;" in site_html


def test_site_archive_survives_rerender_with_rich_nested_content(project):
    # Regression test for the boundary-detection fix: the old idempotent
    # replace matched on a bare `</ul></li>` terminator, which worked only
    # because a bare-title item had no internal tags of its own. Once items
    # carry their own <blockquote>/<p> markup (this fix), that terminator
    # could match an inner tag sequence instead of the real block end.
    # Comment markers replace it specifically to stay correct here.
    _write("data/ranked/2026-W01.json", [_ranked_cluster(excerpt="a real excerpt")])
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(franchise="vendor_watch", primary_source_url="https://vendor.example.com/changelog")],
    )

    render_final_digest("2026-W01")
    render_final_digest("2026-W01")
    render_final_digest("2026-W01")

    with open("site/index.html", encoding="utf-8") as f:
        site_html = f.read()
    assert site_html.count('data-week="2026-W01"') == 1
    assert site_html.count("<li data-week=") == 1
    assert site_html.count("a real excerpt") == 1
    assert site_html.count("Vendor Watch") == 1


# ---------- site archive: idempotency regression ----------


def test_site_archive_replaces_not_duplicates_on_rerender(project):
    """Regression test for the bug the reviewer agent found and reproduced:
    re-rendering the same week used to append a second <li> instead of
    replacing the first, and the initial fix attempt still corrupted the
    HTML (stray trailing </ul></li>) on a second run."""
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry()])

    render_final_digest("2026-W01")
    render_final_digest("2026-W01")
    render_final_digest("2026-W01")

    with open("site/index.html", encoding="utf-8") as f:

        site_html = f.read()
    assert site_html.count('data-week="2026-W01"') == 1
    # Exactly one well-formed block: <li data-week=...><strong>...</strong>
    # <ul>...story items...</ul></li> — no stray closing tags left behind.
    assert site_html.count("<li data-week=") == 1
    assert site_html.count("</ul></li>") == 1


def test_site_archive_keeps_distinct_weeks_separate(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster(cluster_id="c1")])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(cluster_id="c1")])
    _write("data/ranked/2026-W02.json", [_ranked_cluster(cluster_id="c2", title="A second story")])
    _write_draft("digest/draft/2026-W02.json", [_draft_entry(cluster_id="c2", title="A second story")])

    render_final_digest("2026-W01")
    render_final_digest("2026-W02")

    with open("site/index.html", encoding="utf-8") as f:

        site_html = f.read()
    assert 'data-week="2026-W01"' in site_html
    assert 'data-week="2026-W02"' in site_html
    assert site_html.count("<li data-week=") == 2


def test_site_archive_updated_entry_reflects_new_items(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster(cluster_id="c1", title="Original title")])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(cluster_id="c1", title="Original title")])
    render_final_digest("2026-W01")

    _write("data/ranked/2026-W01.json", [_ranked_cluster(cluster_id="c1", title="Corrected title")])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(cluster_id="c1", title="Corrected title")])
    render_final_digest("2026-W01")

    with open("site/index.html", encoding="utf-8") as f:

        site_html = f.read()
    assert "Corrected title" in site_html
    assert "Original title" not in site_html
    assert site_html.count("<li data-week=") == 1


def test_first_issue_placeholder_removed_after_first_render(project):
    with open("site/index.html", encoding="utf-8") as f:
        assert "First issue coming soon" in f.read()
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry()])
    render_final_digest("2026-W01")
    with open("site/index.html", encoding="utf-8") as f:
        assert "First issue coming soon" not in f.read()
