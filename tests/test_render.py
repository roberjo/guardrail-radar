"""Tests for pipeline.render — see docs/technical-spec.md §14, §18.

Runs entirely against a temp working directory (monkeypatch.chdir) so the
module's relative data/digest/site paths are isolated per test. Includes a
regression test for the site-archive duplication/corruption bug found by
the reviewer agent and fixed twice (the first fix looked right but still
corrupted the HTML on a second render) — see CHANGELOG.md.
"""

import json
import os
import re

import pytest

from pipeline.render import (
    _clean_display_title,
    _read_time_minutes,
    build_beehiiv_draft_content,
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


def _write_draft(path: str, items: list, intro: str = "", subject: str = "A test subject line") -> None:
    """digest/draft/<week>.json is {"subject": ..., "intro": ..., "items": [...]}
    — see docs/technical-spec.md §12.2. intro is optional connective
    narrative for the whole issue, added after real user feedback that
    isolated per-item summaries with no frame read as a link list, not a
    newsletter. subject is the Beehiiv subject line, required in practice
    but not enforced by the pipeline (defaulted here like intro).
    """
    _write(path, {"subject": subject, "intro": intro, "items": items})


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


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


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
#
# render_final_digest returns (digest_path, site_path, issue_page_path).
# site_path (site/index.html) now carries only a short teaser per issue —
# the full content (TOC, items, excerpt/note) moved to its own standalone
# page at issue_page_path (site/issues/<iso-week>.html), added after a
# direct user request for past issues linkable on social media with their
# own title/description, not just the homepage's generic preview.


def test_final_digest_renders_note_and_excerpt(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry()])
    digest_path, _site_path, issue_page_path = render_final_digest("2026-W01")
    digest_content = _read(digest_path)
    issue_content = _read(issue_page_path)
    assert "Why this matters to a compliance-constrained engineer." in digest_content
    assert "a real excerpt" in digest_content
    assert "Why this matters to a compliance-constrained engineer." in issue_content
    assert "a real excerpt" in issue_content


def test_final_digest_renders_intro_in_digest_and_issue_page(project):
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
    digest_path, _site_path, issue_page_path = render_final_digest("2026-W01")
    digest_content = _read(digest_path)
    issue_content = _read(issue_page_path)
    assert "A dry, professional aside that ties the week together." in digest_content
    assert "A dry, professional aside that ties the week together." in issue_content
    assert 'class="issue-intro"' in issue_content


def test_final_digest_omits_intro_block_when_not_provided(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry()])  # no intro
    _, _site_path, issue_page_path = render_final_digest("2026-W01")
    assert '<p class="issue-intro"' not in _read(issue_page_path)


def test_final_digest_escapes_intro_html(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft(
        "digest/draft/2026-W01.json", [_draft_entry()], intro='<script>alert(3)</script>'
    )
    _, _site_path, issue_page_path = render_final_digest("2026-W01")
    assert "<script>alert(3)</script>" not in _read(issue_page_path)


def test_final_digest_renders_title_as_headline_hook_as_dek(project):
    # Reverted from an earlier flip that made the hand-written hook the
    # headline: a hook-as-headline reads as generic ad copy and strips the
    # proper nouns (product/company names) a technical reader scans for.
    # The title is the headline again; the hook runs as a one-line "why
    # this matters" dek right underneath it.
    _write("data/ranked/2026-W01.json", [_ranked_cluster(title="A real story")])
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(title="A real story", hook="Proves the agent fix actually held, not just that it passed CI.")],
    )
    digest_path, _site_path, issue_page_path = render_final_digest("2026-W01")
    digest_content = _read(digest_path)
    issue_content = _read(issue_page_path)

    hook_text = "Proves the agent fix actually held, not just that it passed CI."
    # digest markdown: the H3 heading is the title; the hook follows as a
    # plain dek line.
    assert "### [A real story]" in digest_content
    assert digest_content.index("A real story") < digest_content.index(hook_text)
    assert digest_content.index(hook_text) < digest_content.index("a real excerpt")
    # issue page: the <h4> headline is the title; the hook is a dek below it.
    assert '<h4><a href="https://example.com/story">A real story</a></h4>' in issue_content
    assert f'class="item-dek">{hook_text}</p>' in issue_content
    assert issue_content.index(hook_text) < issue_content.index("a real excerpt")


def test_final_digest_omits_dek_when_no_hook(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster(title="A real story")])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(title="A real story", hook="")])
    digest_path, _site_path, issue_page_path = render_final_digest("2026-W01")
    digest_content = _read(digest_path)
    issue_content = _read(issue_page_path)
    assert "### [A real story]" in digest_content
    assert "<h4><a href=\"https://example.com/story\">A real story</a></h4>" in issue_content
    # No hook means no dek — nothing to summarize "why this matters" with.
    assert '<p class="item-dek"' not in issue_content


def test_final_digest_strips_show_hn_prefix_for_display(project):
    # _clean_display_title strips HN's own submission-type metadata
    # ("Show HN:"/"Ask HN:"/"Tell HN:") — it's not part of the author's
    # title, and left in it reads as "this was scraped," not curated.
    raw_title = "Show HN: Proliferate - open source coding agent IDE"
    _write("data/ranked/2026-W01.json", [_ranked_cluster(title=raw_title)])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(title=raw_title, hook="Run every agent from one IDE.")])
    digest_path, _site_path, issue_page_path = render_final_digest("2026-W01")
    digest_content = _read(digest_path)
    issue_content = _read(issue_page_path)
    assert "Show HN:" not in digest_content
    assert "Show HN:" not in issue_content
    assert "Proliferate - open source coding agent IDE" in digest_content
    assert "Proliferate - open source coding agent IDE" in issue_content


def test_clean_display_title_strips_hn_prefixes():
    assert _clean_display_title("Show HN: A real tool") == "A real tool"
    assert _clean_display_title("Ask HN: What do you use?") == "What do you use?"
    assert _clean_display_title("Tell HN: I built a thing") == "I built a thing"
    assert _clean_display_title("A plain title, no prefix") == "A plain title, no prefix"
    assert _clean_display_title("") == ""


def test_final_digest_escapes_hook_html(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft(
        "digest/draft/2026-W01.json", [_draft_entry(hook='<script>alert(4)</script>')]
    )
    _, _site_path, issue_page_path = render_final_digest("2026-W01")
    issue_content = _read(issue_page_path)
    assert "<script>alert(4)</script>" not in issue_content
    assert "&lt;script&gt;" in issue_content


def test_final_digest_toc_groups_by_category_in_fixed_order(project):
    # Added after a direct user request for a table of contents grouped by
    # area/criticality — see docs/technical-spec.md §12.2. Order is
    # hottest-to-coldest (notable, breaking, field_notes, new_product),
    # per a follow-up user request, not urgency-first — regardless of
    # input order — and a category absent from the draft is omitted.
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
            # hook="" here — irrelevant to the TOC, which always links with
            # each item's cleaned title, not the hook.
            _draft_entry(cluster_id="c1", title="A notable one", category="notable", hook=""),
            _draft_entry(cluster_id="c2", title="A breaking one", category="breaking", hook=""),
            _draft_entry(cluster_id="c3", title="A new product one", category="new_product", hook=""),
        ],
    )
    digest_path, _site_path, issue_page_path = render_final_digest("2026-W01")
    digest_content = _read(digest_path)
    issue_content = _read(issue_page_path)

    # Fixed order: Notable / Wow, then Breaking News, then New Products & Tools.
    # issue_content has "&" html-escaped to "&amp;" in the category label.
    assert digest_content.index("Notable / Wow") < digest_content.index("Breaking News")
    assert digest_content.index("Breaking News") < digest_content.index("New Products & Tools")
    assert issue_content.index("Notable / Wow") < issue_content.index("Breaking News")
    assert issue_content.index("Breaking News") < issue_content.index("New Products &amp; Tools")

    # A category with no items (field_notes here) isn't shown at all.
    assert "Field Notes" not in digest_content
    assert "Field Notes" not in issue_content

    assert 'class="toc"' in issue_content
    assert '<a href="#item-c2">A breaking one</a>' in issue_content


def test_final_digest_item_body_order_matches_toc_order_not_draft_order(project):
    # The core of the hottest-to-coldest request: previously the TOC
    # grouped by category but the actual item bodies below it stayed in
    # whatever order the draft happened to list them in — so the TOC
    # could promise "Notable first" while the reader scrolled straight
    # into a new_product item instead. Draft order here is deliberately
    # the reverse of CATEGORY_ORDER to prove the body gets re-sorted, not
    # just the TOC.
    _write(
        "data/ranked/2026-W01.json",
        [
            _ranked_cluster(cluster_id="c1", title="Routine launch"),
            _ranked_cluster(cluster_id="c2", title="Personal essay"),
            _ranked_cluster(cluster_id="c3", title="Urgent incident"),
            _ranked_cluster(cluster_id="c4", title="Wow factor"),
        ],
    )
    _write_draft(
        "digest/draft/2026-W01.json",
        [
            _draft_entry(cluster_id="c1", title="Routine launch", category="new_product"),
            _draft_entry(cluster_id="c2", title="Personal essay", category="field_notes"),
            _draft_entry(cluster_id="c3", title="Urgent incident", category="breaking"),
            _draft_entry(cluster_id="c4", title="Wow factor", category="notable"),
        ],
    )
    digest_path, _site_path, issue_page_path = render_final_digest("2026-W01")
    digest_content = _read(digest_path)
    issue_content = _read(issue_page_path)

    for content in (digest_content, issue_content):
        assert (
            content.index("Wow factor")
            < content.index("Urgent incident")
            < content.index("Personal essay")
            < content.index("Routine launch")
        )


def test_final_digest_toc_anchor_matches_item_id(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster(cluster_id="c1", title="A real story")])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(cluster_id="c1")])
    _, _site_path, issue_page_path = render_final_digest("2026-W01")
    issue_content = _read(issue_page_path)
    assert 'href="#item-c1"' in issue_content
    assert 'id="item-c1"' in issue_content


def test_final_digest_issue_page_has_real_subscribe_link(project):
    # The subscribe CTA was deliberately left commented out until a real
    # Beehiiv URL existed (see docs/technical-spec.md §14) — now that one
    # does (BEEHIIV_SUBSCRIBE_URL), every issue page should carry it.
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry()])
    _, _site_path, issue_page_path = render_final_digest("2026-W01")
    issue_content = _read(issue_page_path)
    assert 'class="subscribe-btn"' in issue_content
    assert 'href="https://guardrail-radar.beehiiv.com/"' in issue_content


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
    digest_path, _site_path, issue_page_path = render_final_digest("2026-W01")
    digest_content = _read(digest_path)
    issue_content = _read(issue_page_path)

    assert "`Notable` ·" in digest_content
    assert "min read" in digest_content
    assert 'class="category-badge">' in issue_content
    assert 'category-icon' in issue_content
    assert "Notable</span>" in issue_content
    assert 'class="read-time">' in issue_content and "min read" in issue_content


def test_hotness_order_bands_by_category_and_ranks_by_score_within_it(project):
    # Direct user request: a true continuous gradient, not 4 fixed
    # swatches — hue must strictly decrease category-to-category
    # (notable hottest, new_product coolest, per CATEGORY_ORDER) and, for
    # items sharing a category, the higher real cluster_score item must
    # get the hotter (lower) hue, not just retain its draft order.
    c1 = _ranked_cluster(cluster_id="c1", title="Notable, low score")
    c1["cluster_score"] = 1.0
    c2 = _ranked_cluster(cluster_id="c2", title="Notable, high score")
    c2["cluster_score"] = 99.0
    c3 = _ranked_cluster(cluster_id="c3", title="A new product")
    _write("data/ranked/2026-W01.json", [c1, c2, c3])
    _write_draft(
        "digest/draft/2026-W01.json",
        [
            _draft_entry(cluster_id="c1", title="Notable, low score", category="notable"),
            _draft_entry(cluster_id="c2", title="Notable, high score", category="notable"),
            _draft_entry(cluster_id="c3", title="A new product", category="new_product"),
        ],
    )
    _, _site_path, issue_page_path = render_final_digest("2026-W01")
    issue_content = _read(issue_page_path)

    # Item order: higher-scoring notable item first, then the lower-scoring
    # one, then new_product last.
    assert (
        issue_content.index("Notable, high score")
        < issue_content.index("Notable, low score")
        < issue_content.index("A new product")
    )
    # Hue: each item's own <li> carries a --hot-hue that strictly increases
    # (cools) from the hottest notable item through to new_product. Scoped
    # to each item's own <li id="item-<cid>"> specifically — the TOC
    # renders its own, separate copy of these same hue values earlier in
    # the page, so a page-wide scan isn't a single monotonic sequence.
    def item_hue(cid: str) -> int:
        match = re.search(rf'id="item-{cid}" style="--hot-hue:(\d+)"', issue_content)
        assert match, f"no --hot-hue found on item {cid!r}"
        return int(match.group(1))

    assert item_hue("c2") < item_hue("c1") < item_hue("c3")


def test_final_digest_each_category_renders_a_hot_hue_style(project):
    # All 4 categories get a real, distinct hue via inline --hot-hue —
    # follow-up to real feedback that even 4 fixed swatches were too
    # coarse; there is no more per-category CSS class to assert on.
    seen_hues = set()
    for i, category in enumerate(["breaking", "new_product", "notable", "field_notes"]):
        cid = f"c{i}"
        _write("data/ranked/2026-W01.json", [_ranked_cluster(cluster_id=cid)])
        _write_draft("digest/draft/2026-W01.json", [_draft_entry(cluster_id=cid, category=category)])
        _, _site_path, issue_page_path = render_final_digest("2026-W01")
        issue_content = _read(issue_page_path)
        assert 'class="category-badge">' in issue_content
        assert '<h4><a href=' in issue_content  # title renders as the headline
        match = re.search(r'--hot-hue:(\d+)', issue_content)
        assert match, f"no --hot-hue found for category {category!r}"
        seen_hues.add(int(match.group(1)))
    assert len(seen_hues) == 4  # each category lands in a distinct hue band


def test_hue_band_order_gives_breaking_the_hottest_hue_despite_reading_order(project):
    # A design-critique pass found CATEGORY_ORDER's reading-order rank
    # (notable, breaking, field_notes, new_product — notable reads first)
    # had been silently reused to also drive hue-band assignment, so
    # `notable` (a curiosity item) owned the alarm-red end of the gradient
    # while `breaking` (an actual incident) rendered in a calmer amber.
    # HUE_BAND_ORDER decouples them: breaking must own the hottest hue
    # regardless of where it falls in reading order.
    _write(
        "data/ranked/2026-W01.json",
        [_ranked_cluster(cluster_id="c1", title="A notable one"), _ranked_cluster(cluster_id="c2", title="A breaking one")],
    )
    _write_draft(
        "digest/draft/2026-W01.json",
        [
            _draft_entry(cluster_id="c1", title="A notable one", category="notable", hook=""),
            _draft_entry(cluster_id="c2", title="A breaking one", category="breaking", hook=""),
        ],
    )
    _, _site_path, issue_page_path = render_final_digest("2026-W01")
    issue_content = _read(issue_page_path)

    def item_hue(cid: str) -> int:
        match = re.search(rf'id="item-{cid}" style="--hot-hue:(\d+)"', issue_content)
        assert match, f"no --hot-hue found on item {cid!r}"
        return int(match.group(1))

    # notable reads first (per CATEGORY_ORDER) but breaking must render hotter.
    assert issue_content.index("A notable one") < issue_content.index("A breaking one")
    assert item_hue("c2") < item_hue("c1")


def test_final_digest_toc_group_shows_item_count(project):
    _write(
        "data/ranked/2026-W01.json",
        [_ranked_cluster(cluster_id="c1"), _ranked_cluster(cluster_id="c2", title="Second story")],
    )
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(cluster_id="c1", category="breaking"), _draft_entry(cluster_id="c2", category="breaking")],
    )
    digest_path, _site_path, issue_page_path = render_final_digest("2026-W01")
    digest_content = _read(digest_path)
    issue_content = _read(issue_page_path)
    assert "Breaking News (2)" in digest_content
    assert 'class="toc-group"' in issue_content
    assert '<span class="count">(2)</span>' in issue_content


def test_final_digest_markdown_bolds_breaking_but_not_other_categories(project):
    # Plain markdown has no color, so BREAKING gets bold+uppercase instead —
    # the same "one category pops, the rest recede" rule the site's color
    # coding follows, translated to what markdown can actually do.
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(category="breaking")])
    digest_path, _, _ = render_final_digest("2026-W01")
    breaking_content = _read(digest_path)
    assert "**BREAKING** ·" in breaking_content
    assert "`Breaking`" not in breaking_content

    _write_draft("digest/draft/2026-W01.json", [_draft_entry(category="notable")])
    digest_path, _, _ = render_final_digest("2026-W01")
    notable_content = _read(digest_path)
    assert "`Notable` ·" in notable_content
    assert "**NOTABLE**" not in notable_content


def test_final_digest_omits_redundant_stats_line_from_issue_page(project):
    # The "In this issue: N items across N sources — ..." line was cut
    # from the per-issue view after a design-critique pass found it
    # repeated, almost verbatim, what the table of contents already
    # conveys better, one scroll below it. It's back only as a homepage
    # teaser summary (see test_homepage_teaser_shows_summary_and_link
    # below) — a genuinely different role, not a regression.
    _write(
        "data/ranked/2026-W01.json",
        [_ranked_cluster(cluster_id="c1"), _ranked_cluster(cluster_id="c2", title="Second story")],
    )
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(cluster_id="c1", category="breaking"), _draft_entry(cluster_id="c2", category="notable")],
    )
    digest_path, _site_path, issue_page_path = render_final_digest("2026-W01")
    digest_content = _read(digest_path)
    issue_content = _read(issue_page_path)
    assert "In this issue:" not in digest_content
    assert 'class="issue-summary"' not in issue_content


def test_final_digest_renders_subject_line_in_markdown_only(project):
    # subject is the Beehiiv subject-field text — required practice, not
    # part of the issue body. Surfaced as a clearly-labeled line at the top
    # of digest/<iso-week>.md for the manual paste-and-send step. It also
    # doubles as the issue page's meta/og/twitter description (a real,
    # deliberate reuse — see _meta_description) but must never appear as
    # visible reader-facing *body* copy on that page, only in <head>.
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft(
        "digest/draft/2026-W01.json", [_draft_entry()], subject="A real, specific subject line"
    )
    digest_path, _site_path, issue_page_path = render_final_digest("2026-W01")
    digest_content = _read(digest_path)
    issue_content = _read(issue_page_path)
    assert "A real, specific subject line" in digest_content
    assert digest_content.index("A real, specific subject line") < digest_content.index("# Guardrail Radar")
    issue_body = issue_content.split("<body>", 1)[1]
    assert "A real, specific subject line" not in issue_body


def test_final_digest_omits_subject_line_when_not_provided(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry()], subject="")
    digest_path, _, _ = render_final_digest("2026-W01")
    assert "Subject line" not in _read(digest_path)


def test_final_digest_excerpt_collapsed_on_issue_page_not_in_markdown(project):
    # Site-only: <details> can't be relied on to survive a paste into
    # Beehiiv, so the emailed digest keeps the excerpt always visible as a
    # plain blockquote.
    _write("data/ranked/2026-W01.json", [_ranked_cluster(excerpt="a real excerpt")])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry()])
    digest_path, _site_path, issue_page_path = render_final_digest("2026-W01")
    digest_content = _read(digest_path)
    issue_content = _read(issue_page_path)
    assert "<details>" not in digest_content
    assert "> a real excerpt" in digest_content
    assert "<details><summary>Read the source excerpt</summary>" in issue_content
    assert "a real excerpt" in issue_content


def test_final_digest_shows_non_weekly_franchise_label(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(franchise="vendor_watch", primary_source_url="https://vendor.example.com/changelog")],
    )
    digest_path, _, _ = render_final_digest("2026-W01")
    content = _read(digest_path)
    assert "Vendor Watch" in content
    assert "Primary source: https://vendor.example.com/changelog" in content


def test_final_digest_escapes_primary_source_url(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(primary_source_url="https://vendor.example.com/*not*markdown*")],
    )
    digest_path, _, _ = render_final_digest("2026-W01")
    content = _read(digest_path)
    assert r"https://vendor.example.com/\*not\*markdown\*" in content


def test_final_digest_omits_link_when_no_http_url_available(project, capsys):
    cluster = _ranked_cluster()
    cluster["url"] = "javascript:alert(1)"
    _write("data/ranked/2026-W01.json", [cluster])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(url="javascript:alert(1)")])
    digest_path, _site_path, issue_page_path = render_final_digest("2026-W01")
    digest_content = _read(digest_path)
    issue_content = _read(issue_page_path)
    assert "javascript:" not in digest_content
    assert "javascript:" not in issue_content
    assert "A real story" in digest_content
    # Scope to the actual issue-item, not the TOC above it — the TOC
    # legitimately contains its own <a href="#item-..."> anchor link to
    # this same item, which isn't the unsafe url this test is guarding
    # against.
    item_html = issue_content.split('class="issue-items"')[1].split("</li>")[0]
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
    digest_path, _, _ = render_final_digest("2026-W01")
    assert os.path.exists(digest_path)


def test_final_digest_html_escapes_untrusted_title_and_url(project):
    malicious_title = '<script>alert(1)</script>'
    _write("data/ranked/2026-W01.json", [_ranked_cluster(title=malicious_title)])
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(title=malicious_title, url='https://example.com/"><script>x</script>')],
    )
    _, _site_path, issue_page_path = render_final_digest("2026-W01")
    issue_html = _read(issue_page_path)
    assert "<script>alert(1)</script>" not in issue_html
    assert "&lt;script&gt;" in issue_html


# ---------- issue page: full content (not just a bare title link) ----------


def test_issue_page_includes_excerpt_and_note_not_just_title(project):
    # Regression test: the site previously rendered only a bare
    # <li><a>title</a></li> per item — the actual commentary (note) and
    # excerpt went into digest/<week>.md but never reached the public page.
    # Found by the user looking at the real deployed site, not by a test —
    # there wasn't one that checked this.
    _write("data/ranked/2026-W01.json", [_ranked_cluster(excerpt="a real excerpt")])
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(note="Why this matters to a compliance-constrained engineer.")],
    )
    _, _site_path, issue_page_path = render_final_digest("2026-W01")
    issue_html = _read(issue_page_path)
    assert "a real excerpt" in issue_html
    assert "Why this matters to a compliance-constrained engineer." in issue_html


def test_issue_page_shows_franchise_tag_and_primary_source(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(franchise="vendor_watch", primary_source_url="https://vendor.example.com/changelog")],
    )
    _, _site_path, issue_page_path = render_final_digest("2026-W01")
    issue_html = _read(issue_page_path)
    assert "Vendor Watch" in issue_html
    assert 'href="https://vendor.example.com/changelog"' in issue_html


def test_issue_page_omits_franchise_tag_for_plain_weekly_items(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(franchise="weekly")])
    _, _site_path, issue_page_path = render_final_digest("2026-W01")
    assert '<span class="franchise-tag"' not in _read(issue_page_path)


def test_issue_page_escapes_note_and_excerpt_html(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster(excerpt='<img src=x onerror="alert(1)">')])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(note='<script>alert(2)</script>')])
    _, _site_path, issue_page_path = render_final_digest("2026-W01")
    issue_html = _read(issue_page_path)
    assert "<script>alert(2)</script>" not in issue_html
    assert "<img src=x" not in issue_html
    assert "&lt;script&gt;" in issue_html


def test_issue_page_rerender_overwrites_not_duplicates(project):
    # The issue page is a dedicated file per iso-week (not an insert into a
    # shared document), so a re-render is a plain overwrite — no marker
    # machinery needed there, unlike the homepage archive below. Still
    # worth a regression check that content doesn't somehow accumulate.
    _write("data/ranked/2026-W01.json", [_ranked_cluster(excerpt="a real excerpt")])
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(franchise="vendor_watch", primary_source_url="https://vendor.example.com/changelog")],
    )

    render_final_digest("2026-W01")
    render_final_digest("2026-W01")
    _, _site_path, issue_page_path = render_final_digest("2026-W01")

    issue_html = _read(issue_page_path)
    assert issue_html.count("a real excerpt") == 1
    assert issue_html.count("Vendor Watch") == 1


def test_issue_page_has_og_and_twitter_meta_using_subject(project):
    # Added after a direct user request for issues linkable on social
    # media — a shared link needs its own title/description to produce a
    # correct preview card, not the homepage's generic one. subject
    # (already written as one punchy sentence for the Beehiiv send)
    # doubles as the social description.
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft(
        "digest/draft/2026-W01.json", [_draft_entry()], subject="A real, specific subject line"
    )
    _, _site_path, issue_page_path = render_final_digest("2026-W01")
    issue_html = _read(issue_page_path)
    assert "<title>Guardrail Radar — 2026-W01</title>" in issue_html
    assert 'property="og:title" content="Guardrail Radar — 2026-W01"' in issue_html
    assert 'property="og:description" content="A real, specific subject line"' in issue_html
    assert 'property="og:url" content="https://roberjo.github.io/guardrail-radar/issues/2026-W01.html"' in issue_html
    assert 'name="twitter:card" content="summary_large_image"' in issue_html
    assert 'property="og:image" content="https://roberjo.github.io/guardrail-radar/og-image.png"' in issue_html


def test_issue_page_meta_description_falls_back_to_intro_then_generic(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft(
        "digest/draft/2026-W01.json", [_draft_entry()], subject="", intro="A connective narrative for the week."
    )
    _, _site_path, issue_page_path = render_final_digest("2026-W01")
    assert 'og:description" content="A connective narrative for the week."' in _read(issue_page_path)

    _write_draft("digest/draft/2026-W01.json", [_draft_entry()], subject="", intro="")
    _, _site_path, issue_page_path = render_final_digest("2026-W01")
    assert 'og:description" content="Guardrail Radar — the 2026-W01 issue."' in _read(issue_page_path)


# ---------- homepage: teaser cards, linking to the issue page ----------


def test_homepage_teaser_shows_summary_and_link(project):
    _write(
        "data/ranked/2026-W01.json",
        [_ranked_cluster(cluster_id="c1"), _ranked_cluster(cluster_id="c2", title="Second story")],
    )
    _write_draft(
        "digest/draft/2026-W01.json",
        [_draft_entry(cluster_id="c1", category="breaking"), _draft_entry(cluster_id="c2", category="notable")],
        subject="This week has a real subject line",
    )
    _, site_path, _issue_page_path = render_final_digest("2026-W01")
    site_content = _read(site_path)

    assert '<a href="issues/2026-W01.html">2026-W01</a>' in site_content
    assert "This week has a real subject line" in site_content
    assert "2 items across 1 source — 1 notable, 1 breaking." in site_content
    assert '<a class="teaser-link" href="issues/2026-W01.html">Read the full issue →</a>' in site_content
    # The homepage no longer carries the full item content itself.
    assert "issue-items" not in site_content
    assert 'class="toc"' not in site_content


def test_homepage_teaser_description_falls_back_to_intro_when_no_subject(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft(
        "digest/draft/2026-W01.json", [_draft_entry()], subject="", intro="A short connective aside for the week."
    )
    _, site_path, _ = render_final_digest("2026-W01")
    assert "A short connective aside for the week." in _read(site_path)


def test_site_archive_replaces_not_duplicates_on_rerender(project):
    """Regression test for the bug the reviewer agent found and reproduced:
    re-rendering the same week used to append a second <li> instead of
    replacing the first, and the initial fix attempt still corrupted the
    HTML (stray trailing </ul></li>) on a second run. Still relevant with
    the teaser-card content: the idempotent marker mechanism is unchanged,
    only the content it wraps got smaller."""
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry()])

    render_final_digest("2026-W01")
    render_final_digest("2026-W01")
    render_final_digest("2026-W01")

    site_html = _read("site/index.html")
    assert site_html.count('data-week="2026-W01"') == 1
    assert site_html.count("<li data-week=") == 1


def test_site_archive_keeps_distinct_weeks_separate(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster(cluster_id="c1")])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(cluster_id="c1")])
    _write("data/ranked/2026-W02.json", [_ranked_cluster(cluster_id="c2", title="A second story")])
    _write_draft("digest/draft/2026-W02.json", [_draft_entry(cluster_id="c2", title="A second story")])

    render_final_digest("2026-W01")
    render_final_digest("2026-W02")

    site_html = _read("site/index.html")
    assert 'data-week="2026-W01"' in site_html
    assert 'data-week="2026-W02"' in site_html
    assert site_html.count("<li data-week=") == 2
    assert os.path.exists("site/issues/2026-W01.html")
    assert os.path.exists("site/issues/2026-W02.html")


def test_site_archive_updated_entry_reflects_new_items(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster(cluster_id="c1", title="Original title")])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(cluster_id="c1", title="Original title")])
    render_final_digest("2026-W01")

    _write("data/ranked/2026-W01.json", [_ranked_cluster(cluster_id="c1", title="Corrected title")])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(cluster_id="c1", title="Corrected title")])
    _, _site_path, issue_page_path = render_final_digest("2026-W01")

    issue_html = _read(issue_page_path)
    assert "Corrected title" in issue_html
    assert "Original title" not in issue_html
    site_html = _read("site/index.html")
    assert site_html.count("<li data-week=") == 1


def test_first_issue_placeholder_removed_after_first_render(project):
    assert "First issue coming soon" in _read("site/index.html")
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry()])
    render_final_digest("2026-W01")
    assert "First issue coming soon" not in _read("site/index.html")


# ---------- beehiiv draft content ----------


def test_build_beehiiv_draft_content_uses_subject_as_title(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry()], subject="A punchy subject line")
    title, _body = build_beehiiv_draft_content("2026-W01")
    assert title == "A punchy subject line"


def test_build_beehiiv_draft_content_falls_back_to_generic_title_without_subject(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry()], subject="")
    title, _body = build_beehiiv_draft_content("2026-W01")
    assert title == "Guardrail Radar — 2026-W01"


def test_build_beehiiv_draft_content_body_has_no_site_only_markup(project):
    # Beehiiv's editor can't load ISSUE_PAGE_CSS, so the body must not
    # depend on it: no --hot-hue custom properties, no <details> collapse
    # (same reason digest/<iso-week>.md avoids it).
    _write("data/ranked/2026-W01.json", [_ranked_cluster(title="A real story", excerpt="a real excerpt")])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(title="A real story")], intro="A short intro.")
    _title, body = build_beehiiv_draft_content("2026-W01")
    assert "--hot-hue" not in body
    assert "<details>" not in body
    assert "A short intro." in body
    assert "A real story" in body
    assert "a real excerpt" in body


def test_build_beehiiv_draft_content_orders_items_hottest_first(project):
    _write(
        "data/ranked/2026-W01.json",
        [
            _ranked_cluster(cluster_id="c1", title="Routine launch"),
            _ranked_cluster(cluster_id="c2", title="Wow factor"),
        ],
    )
    _write_draft(
        "digest/draft/2026-W01.json",
        [
            _draft_entry(cluster_id="c1", title="Routine launch", category="new_product"),
            _draft_entry(cluster_id="c2", title="Wow factor", category="notable"),
        ],
    )
    _title, body = build_beehiiv_draft_content("2026-W01")
    assert body.index("Wow factor") < body.index("Routine launch")


def test_build_beehiiv_draft_content_refuses_unresolved_blocked_entries(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster(cluster_id="c1")])
    _write_draft("digest/draft/2026-W01.json", [_draft_entry(cluster_id="c1")])
    _write(
        "digest/verification/2026-W01.json",
        [{"cluster_id": "c1", "status": "blocked"}],
    )
    with pytest.raises(RuntimeError, match="unresolved blocked"):
        build_beehiiv_draft_content("2026-W01")
