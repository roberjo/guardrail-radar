"""Rendering — see docs/technical-spec.md §14.

Two targets:
  --target review-packet   data/ranked/<week>.json -> digest/review/<week>.md
  --target final-digest    digest/draft/<week>.json (+ verification) ->
                            digest/<week>.md and site/index.html

Both escape third-party text before it reaches HTML/Markdown output —
titles and excerpts originate from Reddit/HN/GitHub/etc. and are not
trusted input.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
from urllib.parse import urlsplit

from pipeline.io_utils import iso_week_str, read_json

SITE_ARCHIVE_MARKER = (
    "<!-- pipeline/render.py appends one <li> per published week here, "
    "per docs/technical-spec.md §14 -->"
)

# Fixed reading order — hottest to coldest, not urgency-first — applied to
# both the table of contents and the actual item order in the issue body.
# See docs/technical-spec.md §12.2. A category absent from the week's draft
# is simply omitted, not shown empty.
#
# Direct user request: lead with the most interesting item (notable/"wow"),
# not the most urgent one — the opposite of the inverted-pyramid convention
# most comparable digest newsletters (TLDR, tl;dr sec, The Batch) use, where
# the lead slot goes to the day's biggest/most urgent story. This follows a
# different, equally real convention instead — engagement-first newsletters
# (Morning Brew is the standard example) deliberately open with whatever's
# most compelling that day to hook the reader, saving routine content for
# when momentum is already established, rather than leading with duty-read
# urgency. new_product goes last on the user's own read that routine
# launches are the least engaging category most weeks.
CATEGORY_ORDER = ["notable", "breaking", "field_notes", "new_product"]
CATEGORY_LABELS = {
    "breaking": "Breaking News",
    "new_product": "New Products & Tools",
    "notable": "Notable / Wow",
    "field_notes": "Field Notes",
}
# Short badge label per item — distinct from CATEGORY_LABELS' longer TOC
# section headings. See docs/technical-spec.md §14 (format audit).
CATEGORY_BADGE_LABELS = {
    "breaking": "Breaking",
    "new_product": "New Product",
    "notable": "Notable",
    "field_notes": "Field Notes",
}

WORDS_PER_MINUTE = 200


def _item_anchor(cluster_id: str) -> str:
    return f"item-{cluster_id}"


def _read_time_minutes(*texts: str) -> int:
    """Rounded reading-time estimate at WORDS_PER_MINUTE, minimum 1.

    Added after a format audit against comparable newsletters (TLDR, The
    Batch) that all surface a read-time signal per item — pure text-derived
    from fields already on the entry, no new drafted data needed.
    """
    word_count = sum(len(t.split()) for t in texts)
    return max(1, round(word_count / WORDS_PER_MINUTE))


def _md_escape(text: str) -> str:
    return re.sub(r"([\\`*_\[\]])", r"\\\1", text or "")


def _is_http_url(url: str) -> bool:
    return bool(url) and urlsplit(url).scheme in ("http", "https")


def _load_draft(draft_path: str) -> tuple[str, list[dict]]:
    """Returns (intro, items). See digest-draft-schema §12.2.

    `intro` is a short connective narrative for the whole issue — dry wit,
    still professional (see docs/editorial-guidelines.md) — written once
    per issue, not per item. Added after real user feedback on the first
    live issue: three isolated per-item summaries with no frame or
    synthesis read as a bare link list, not a newsletter. Optional — an
    empty string is valid and renders nothing, so a thin week doesn't force
    a forced-sounding intro.
    """
    data = read_json(draft_path)
    return data.get("intro", ""), data.get("items", [])


# (singular, plural) phrasing per category for _issue_stats_line below.
_CATEGORY_STAT_WORDS = {
    "breaking": ("breaking", "breaking"),
    "new_product": ("new product", "new products"),
    "notable": ("notable", "notable"),
    "field_notes": ("field note", "field notes"),
}


def _issue_stats_line(draft: list[dict], ranked_by_cluster: dict) -> str:
    if not draft:
        return ""

    sources: set[str] = set()
    category_counts: dict[str, int] = {}
    for entry in draft:
        cluster = ranked_by_cluster.get(entry["cluster_id"], {})
        item_sources = cluster.get("cluster_sources") or ([cluster["source"]] if cluster.get("source") else [])
        sources.update(item_sources)
        category = entry.get("category", "new_product")
        category_counts[category] = category_counts.get(category, 0) + 1

    parts = []
    for category in CATEGORY_ORDER:
        count = category_counts.get(category, 0)
        if not count:
            continue
        singular, plural = _CATEGORY_STAT_WORDS[category]
        parts.append(f"{count} {singular if count == 1 else plural}")

    item_word = "item" if len(draft) == 1 else "items"
    source_word = "source" if len(sources) == 1 else "sources"
    summary = f"In this issue: {len(draft)} {item_word} across {len(sources)} {source_word}"
    if parts:
        summary += " — " + ", ".join(parts)
    return summary + "."


def render_review_packet(iso_week: str) -> str:
    ranked_path = os.path.join("data", "ranked", f"{iso_week}.json")
    clusters = read_json(ranked_path)

    lines = [
        f"# Guardrail Radar — review packet — {iso_week}",
        "",
        ("Extractive only. No commentary has been written yet — this is the "
        "input to the draft-digest skill, not a draft itself."),
        "",
    ]

    for i, cluster in enumerate(clusters, start=1):
        title = _md_escape(cluster.get("title", "(untitled)"))
        # A raw `)` in the url would prematurely close the markdown link
        # syntax below and spill the rest of the url as stray trailing
        # text — _md_escape isn't used here since backslash-escaping isn't
        # meaningful inside a markdown link target; percent-encode instead.
        url = cluster.get("url", "").replace(")", "%29")
        sources = ", ".join(cluster.get("cluster_sources") or [cluster.get("source", "")])
        score = cluster.get("cluster_score", 0)
        excerpt_status = cluster.get("excerpt_status", "none")
        excerpt = cluster.get("cluster_excerpt", "")

        lines.append(f"## {i}. [{title}]({url})")
        lines.append(f"- **cluster_id:** `{cluster.get('cluster_id', '')}`")
        lines.append(f"- **source(s):** {sources}  |  **score:** {score:.2f}")
        if excerpt_status == "none" or not excerpt:
            lines.append("- **excerpt:** _[insufficient source text — skip or flag, do not draft from nothing]_")
        else:
            lines.append(f"- **excerpt:** {_md_escape(excerpt)}")
        lines.append("")

    return "\n".join(lines)


def render_final_digest(iso_week: str) -> tuple[str, str]:
    draft_path = os.path.join("digest", "draft", f"{iso_week}.json")
    ranked_path = os.path.join("data", "ranked", f"{iso_week}.json")
    verification_path = os.path.join("digest", "verification", f"{iso_week}.json")

    intro, draft = _load_draft(draft_path)
    ranked_by_cluster = {c["cluster_id"]: c for c in read_json(ranked_path)}

    # Reorder items hottest-to-coldest (CATEGORY_ORDER) before anything
    # renders, so the actual reading order in digest/<week>.md and
    # site/index.html matches the table of contents instead of just the
    # TOC reflecting it while the body stays in whatever order the draft
    # happened to list items in. Stable sort: items keep their relative
    # order within a category (their original ranked order).
    category_rank = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    draft = sorted(
        draft, key=lambda e: category_rank.get(e.get("category", "new_product"), len(CATEGORY_ORDER))
    )

    verification_by_cluster = {}
    if os.path.exists(verification_path):
        for record in read_json(verification_path):
            verification_by_cluster[record["cluster_id"]] = record

    unresolved = []
    for entry in draft:
        record = verification_by_cluster.get(entry["cluster_id"], {})
        if record.get("status") == "blocked" and not entry.get("approved"):
            unresolved.append(entry["cluster_id"])
    if unresolved:
        raise RuntimeError(
            f"Refusing to render: unresolved blocked entries {unresolved}. "
            "Fix the draft or drop the item — see docs/technical-spec.md §13."
        )

    lines_md = [f"# Guardrail Radar — {iso_week}", ""]

    # "In this issue" line — item count, distinct source count, category
    # breakdown. Entirely derived from data already loaded above; no new
    # drafted field needed. See docs/technical-spec.md §14 (format audit).
    stats_line = _issue_stats_line(draft, ranked_by_cluster)
    stats_html = ""
    if stats_line:
        lines_md.append(stats_line)
        lines_md.append("")
        stats_html = f'<p class="issue-stats">{html.escape(stats_line)}</p>'

    intro_html = ""
    if intro:
        lines_md.append(intro)
        lines_md.append("")
        intro_html = f"<p class=\"issue-intro\">{html.escape(intro)}</p>"

    # Table of contents, grouped by category (breaking/new_product/notable/
    # field_notes — see docs/technical-spec.md §12.2), added after a direct
    # user request. Preserves each item's ranked order within its category;
    # a category with no items that week is omitted, not shown empty.
    toc_groups: dict[str, list[tuple[str, str]]] = {c: [] for c in CATEGORY_ORDER}
    for entry in draft:
        category = entry.get("category", "new_product")
        title = entry.get("title") or ranked_by_cluster.get(entry["cluster_id"], {}).get("title", "(untitled)")
        toc_groups.setdefault(category, []).append((title, entry["cluster_id"]))

    toc_html_parts = []
    for category in CATEGORY_ORDER:
        items = toc_groups.get(category, [])
        if not items:
            continue
        label = CATEGORY_LABELS[category]
        lines_md.append(f"**{label} ({len(items)})**")
        for title, cluster_id in items:
            lines_md.append(f"- {_md_escape(title)}")
        lines_md.append("")

        toc_links = "".join(
            f'<li><a href="#{_item_anchor(cid)}">{html.escape(title)}</a></li>' for title, cid in items
        )
        # category class drives the left-border/heading color per group in
        # site CSS — same color used on that category's item badges, so the
        # TOC and the items below it read as one consistent color system
        # rather than two unrelated conventions.
        toc_html_parts.append(
            f'<div class="toc-group {category}"><h4>{html.escape(label)} '
            f'<span class="count">({len(items)})</span></h4><ul>{toc_links}</ul></div>'
        )
    toc_html = f'<nav class="toc">{"".join(toc_html_parts)}</nav>' if toc_html_parts else ""

    archive_items_html = []

    for entry in draft:
        cluster = ranked_by_cluster.get(entry["cluster_id"], {})
        title = entry.get("title") or cluster.get("title", "(untitled)")
        url = entry.get("url") or cluster.get("url", "")
        if not _is_http_url(url):
            print(f"[render] WARNING: entry {entry['cluster_id']!r} has no safe http(s) url — rendering title only, no link", file=sys.stderr)
            url = ""
        excerpt = cluster.get("cluster_excerpt", "")
        hook = entry.get("hook", "")
        note = entry.get("note", "")
        franchise = entry.get("franchise", "weekly")
        category = entry.get("category", "new_product")
        read_minutes = _read_time_minutes(hook, excerpt, note)

        if url:
            lines_md.append(f"### [{_md_escape(title)}]({url})")
        else:
            lines_md.append(f"### {_md_escape(title)}")
        if franchise != "weekly":
            lines_md.append(f"_{franchise.replace('_', ' ').title()}_")
        badge_label = CATEGORY_BADGE_LABELS.get(category, category)
        # Plain markdown has no color, so urgency has to read from emphasis
        # instead: BREAKING is bold+uppercase, every other category stays
        # in quiet inline code — same "one category pops, the rest recede"
        # rule the site's color-coding follows.
        if category == "breaking":
            lines_md.append(f"**{badge_label.upper()}** · {read_minutes} min read")
        else:
            lines_md.append(f"`{badge_label}` · {read_minutes} min read")
        if hook:
            lines_md.append(f"**{_md_escape(hook)}**")
        if excerpt:
            lines_md.append(f"> {_md_escape(excerpt)}")
        lines_md.append("")
        lines_md.append(note)
        if entry.get("primary_source_url"):
            lines_md.append(f"\nPrimary source: {_md_escape(entry['primary_source_url'])}")
        lines_md.append("")

        archive_items_html.append(
            _render_archive_item_html(
                entry["cluster_id"], title, url, hook, excerpt, note, franchise, category, read_minutes, entry
            )
        )

    digest_md = "\n".join(lines_md)
    digest_path = os.path.join("digest", f"{iso_week}.md")
    with open(digest_path, "w", encoding="utf-8") as f:
        f.write(digest_md)

    site_path = _update_site_archive(iso_week, archive_items_html, intro_html, toc_html, stats_html)
    return digest_path, site_path


def _render_archive_item_html(
    cluster_id: str,
    title: str,
    url: str,
    hook: str,
    excerpt: str,
    note: str,
    franchise: str,
    category: str,
    read_minutes: int,
    entry: dict,
) -> str:
    """One item's full content for the site — title, hook, excerpt, note,
    franchise label, primary source. Previously this rendered only a bare
    linked title, dropping the actual commentary (the entire point of the
    newsletter) from the one place the public site shows it — the full
    text still went into digest/<week>.md, just never into site/index.html,
    despite docs/technical-spec.md §14 saying the site gets "the same
    content." Found by the user looking at the real deployed site.

    `hook` renders right after the title, ahead of the excerpt/note —
    added after real user feedback that readers need a one-sentence,
    plain-English reason an item is worth their time before the longer,
    more skeptical note (see docs/technical-spec.md §12.2).

    The returned <li> carries a stable id="item-<cluster_id>" so the
    table-of-contents nav built in render_final_digest can link straight
    to it.

    badge-row (franchise tag + category badge + read-time) and the
    <details>-collapsed excerpt were added after a format audit against
    comparable newsletters (TLDR, tl;dr sec, The Batch) — category is
    meant to register before a reader parses the headline, and the
    verbatim source excerpt is one click deeper rather than always-open
    text, matching the audit's scanability recommendations. The excerpt
    collapse is site-only: <details> can't be relied on to survive a
    paste into Substack/Beehiiv, so digest/<week>.md keeps the excerpt
    always visible.

    Each of the 4 categories now gets its own color (not just breaking) —
    a follow-up to real feedback that at-a-glance scanning needed more
    than "breaking vs. everything else." The same category class drives
    the badge dot, the hook's callout accent, the item's left-border
    stripe, and the matching TOC group's heading color, so the whole page
    reads as one consistent color system instead of an isolated badge.
    """
    heading = f'<a href="{html.escape(url)}">{html.escape(title)}</a>' if url else html.escape(title)
    parts = [f"<h4>{heading}</h4>"]

    badges = []
    if franchise and franchise != "weekly":
        label = html.escape(franchise.replace("_", " ").title())
        badges.append(f'<span class="franchise-tag">{label}</span>')
    category_label = html.escape(CATEGORY_BADGE_LABELS.get(category, category))
    badges.append(
        f'<span class="category-badge {category}"><span class="dot"></span>{category_label}</span>'
    )
    badges.append(f'<span class="read-time">{read_minutes} min read</span>')
    parts.append(f'<div class="badge-row">{"".join(badges)}</div>')

    if hook:
        parts.append(f'<p class="item-hook {category}">{html.escape(hook)}</p>')

    if excerpt:
        parts.append(
            "<details><summary>Read the source excerpt</summary>"
            f"<blockquote>{html.escape(excerpt)}</blockquote></details>"
        )

    if note:
        parts.append(f"<p>{html.escape(note)}</p>")

    primary = entry.get("primary_source_url")
    if primary and _is_http_url(primary):
        parts.append(
            f'<p class="primary-source">Primary source: '
            f'<a href="{html.escape(primary)}">{html.escape(primary)}</a></p>'
        )

    anchor = html.escape(_item_anchor(cluster_id), quote=True)
    category_attr = html.escape(category, quote=True)
    return f'<li class="issue-item {category_attr}" id="{anchor}">{"".join(parts)}</li>'


def _update_site_archive(
    iso_week: str,
    item_html_list: list[str],
    intro_html: str = "",
    toc_html: str = "",
    stats_html: str = "",
) -> str:
    """Insert/replace this week's archive entry — idempotent on re-run.

    Re-running weekly-verify-and-publish for a week that already has an
    archive entry (e.g. to fix a typo and re-render) used to append a
    second <li> instead of replacing the first — found by the reviewer
    agent via an actual reproduction, not a hypothetical.

    Each week's block is now wrapped in a pair of HTML-comment markers
    rather than located by matching structural tags: the first fix used
    `data-week` plus a `</ul></li>` terminator, which broke again the
    moment item content grew past a bare linked title (`_render_archive_
    item_html` above nests its own <blockquote>/<p> tags, and any of those
    can end in `</li>`-adjacent sequences a generic tag-matching regex
    can't tell apart from the block's real end). Comment markers can't be
    confused with structural HTML at any nesting depth, so this stays
    correct regardless of how much richer an item's content gets.
    """
    site_path = os.path.join("site", "index.html")
    with open(site_path, encoding="utf-8") as f:
        html_text = f.read()

    week_attr = html.escape(iso_week, quote=True)
    start_marker = f"<!-- week:{week_attr} -->"
    end_marker = f"<!-- /week:{week_attr} -->"
    week_block = (
        f'{start_marker}<li data-week="{week_attr}"><h3 class="week-heading">{html.escape(iso_week)}</h3>'
        + stats_html
        + intro_html
        + toc_html
        + '<ul class="issue-items">' + "".join(item_html_list) + f"</ul></li>{end_marker}"
    )

    existing_pattern = re.compile(re.escape(start_marker) + r".*?" + re.escape(end_marker), re.DOTALL)
    if existing_pattern.search(html_text):
        html_text = existing_pattern.sub(week_block, html_text, count=1)
    elif SITE_ARCHIVE_MARKER in html_text:
        html_text = html_text.replace(SITE_ARCHIVE_MARKER, SITE_ARCHIVE_MARKER + "\n        " + week_block)
    else:
        html_text = html_text.replace("<ul>", "<ul>\n        " + week_block, 1)

    html_text = re.sub(r'\s*<p class="empty">First issue coming soon\.</p>\n?', "\n", html_text)

    with open(site_path, "w", encoding="utf-8") as f:
        f.write(html_text)
    return site_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["review-packet", "final-digest"], required=True)
    parser.add_argument("--iso-week", default=None)
    args = parser.parse_args()

    iso_week = args.iso_week or iso_week_str()

    if args.target == "review-packet":
        content = render_review_packet(iso_week)
        out_path = os.path.join("digest", "review", f"{iso_week}.md")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[render] wrote {out_path}")
    else:
        digest_path, site_path = render_final_digest(iso_week)
        print(f"[render] wrote {digest_path} and updated {site_path}")


if __name__ == "__main__":
    main()
