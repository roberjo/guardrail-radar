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

from pipeline.render import render_final_digest, render_review_packet

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
    _write("digest/draft/2026-W01.json", [_draft_entry()])
    digest_path, _site_path = render_final_digest("2026-W01")
    with open(digest_path, encoding="utf-8") as f:
        content = f.read()
    assert "Why this matters to a compliance-constrained engineer." in content
    assert "a real excerpt" in content


def test_final_digest_shows_non_weekly_franchise_label(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write(
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
    _write(
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
    _write("digest/draft/2026-W01.json", [_draft_entry(url="javascript:alert(1)")])
    digest_path, site_path = render_final_digest("2026-W01")
    with open(digest_path, encoding="utf-8") as f:
        digest_content = f.read()
    with open(site_path, encoding="utf-8") as f:
        site_content = f.read()
    assert "javascript:" not in digest_content
    assert "javascript:" not in site_content
    assert "A real story" in digest_content
    assert "<a href" not in site_content.split('data-week="2026-W01"')[1].split("</li>")[0]


def test_final_digest_refuses_when_blocked_and_unapproved(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write("digest/draft/2026-W01.json", [_draft_entry()])
    _write(
        "digest/verification/2026-W01.json",
        [{"cluster_id": "c1", "title": "A real story", "status": "blocked", "reasons": ["url failed"]}],
    )
    with pytest.raises(RuntimeError, match="unresolved blocked entries"):
        render_final_digest("2026-W01")
    assert not os.path.exists("digest/2026-W01.md")


def test_final_digest_proceeds_when_blocked_entry_is_approved(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster()])
    _write("digest/draft/2026-W01.json", [_draft_entry(approved=True, approved_reason="checked by hand")])
    _write(
        "digest/verification/2026-W01.json",
        [{"cluster_id": "c1", "title": "A real story", "status": "blocked", "reasons": ["url failed"]}],
    )
    digest_path, _ = render_final_digest("2026-W01")
    assert os.path.exists(digest_path)


def test_final_digest_html_escapes_untrusted_title_and_url(project):
    malicious_title = '<script>alert(1)</script>'
    _write("data/ranked/2026-W01.json", [_ranked_cluster(title=malicious_title)])
    _write(
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
    _write(
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
    _write(
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
    _write("digest/draft/2026-W01.json", [_draft_entry(franchise="weekly")])
    _, site_path = render_final_digest("2026-W01")
    with open(site_path, encoding="utf-8") as f:
        site_html = f.read()
    assert "franchise-tag" not in site_html


def test_site_archive_escapes_note_and_excerpt_html(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster(excerpt='<img src=x onerror="alert(1)">')])
    _write("digest/draft/2026-W01.json", [_draft_entry(note='<script>alert(2)</script>')])
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
    _write(
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
    _write("digest/draft/2026-W01.json", [_draft_entry()])

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
    _write("digest/draft/2026-W01.json", [_draft_entry(cluster_id="c1")])
    _write("data/ranked/2026-W02.json", [_ranked_cluster(cluster_id="c2", title="A second story")])
    _write("digest/draft/2026-W02.json", [_draft_entry(cluster_id="c2", title="A second story")])

    render_final_digest("2026-W01")
    render_final_digest("2026-W02")

    with open("site/index.html", encoding="utf-8") as f:

        site_html = f.read()
    assert 'data-week="2026-W01"' in site_html
    assert 'data-week="2026-W02"' in site_html
    assert site_html.count("<li data-week=") == 2


def test_site_archive_updated_entry_reflects_new_items(project):
    _write("data/ranked/2026-W01.json", [_ranked_cluster(cluster_id="c1", title="Original title")])
    _write("digest/draft/2026-W01.json", [_draft_entry(cluster_id="c1", title="Original title")])
    render_final_digest("2026-W01")

    _write("data/ranked/2026-W01.json", [_ranked_cluster(cluster_id="c1", title="Corrected title")])
    _write("digest/draft/2026-W01.json", [_draft_entry(cluster_id="c1", title="Corrected title")])
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
    _write("digest/draft/2026-W01.json", [_draft_entry()])
    render_final_digest("2026-W01")
    with open("site/index.html", encoding="utf-8") as f:
        assert "First issue coming soon" not in f.read()
