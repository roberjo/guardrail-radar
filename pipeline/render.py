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

# The real, live GitHub Pages URL for this project — confirmed via
# `gh api repos/roberjo/guardrail-radar/pages`, not guessed. Used to build
# absolute canonical/og:url values on each standalone issue page, which
# social platforms require for a correct link preview (a relative or
# missing url falls back to whatever the crawler happened to fetch).
SITE_BASE_URL = "https://roberjo.github.io/guardrail-radar"

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

# Separate from CATEGORY_ORDER above: which category owns the hottest
# (reddest) end of the color gradient. A design-critique pass found these
# two concerns had been silently coupled — reusing CATEGORY_ORDER's reading-
# order rank to also drive hue meant `notable` (a curiosity item) rendered
# as the alarm-red end of the gradient while `breaking` (an actual security
# incident) sat in a calmer amber. For this audience specifically, red
# reads as "incident" — so `breaking` owns that end of the gradient
# regardless of where it falls in reading order. The engagement-first
# reading order above is unchanged; only which color each category gets is
# decoupled from it.
HUE_BAND_ORDER = ["breaking", "notable", "field_notes", "new_product"]
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

# One small inline glyph per category, added after a design-critique pass
# flagged the page as pure text with no visual texture anywhere. Each is a
# minimal 16x16 path using currentColor, so it inherits the item's own
# --hot-hue automatically with no separate color wiring — same mechanism
# the badge/border/dot already use. Kept intentionally tiny and simple
# (site-only, not in the plain-text markdown digest).
CATEGORY_ICON_SVG = {
    "breaking": (
        '<svg class="category-icon" viewBox="0 0 16 16" aria-hidden="true">'
        '<path fill="currentColor" d="M8 1.3 15 14H1L8 1.3Zm0 4.2-.7 5h1.4l-.7-5ZM8 11.2a.9.9 0 1 0 0 1.8.9.9 0 0 0 0-1.8Z"/>'
        "</svg>"
    ),
    "notable": (
        '<svg class="category-icon" viewBox="0 0 16 16" aria-hidden="true">'
        '<path fill="currentColor" d="M8 0l1.6 5.4L15 7l-5.4 1.6L8 14l-1.6-5.4L1 7l5.4-1.6L8 0Z"/>'
        "</svg>"
    ),
    "field_notes": (
        '<svg class="category-icon" viewBox="0 0 16 16" aria-hidden="true">'
        '<path fill="currentColor" d="M3 3h3.2c0 3-1 4.6-2.6 5.2L3 6.7V3Zm6.8 0H13c0 3-1 4.6-2.6 5.2L9.8 6.7V3Z"/>'
        "</svg>"
    ),
    "new_product": (
        '<svg class="category-icon" viewBox="0 0 16 16" aria-hidden="true">'
        '<path fill="currentColor" d="M8 1 14.5 4.5V11.5L8 15 1.5 11.5V4.5L8 1Zm0 2.3L3.6 5.6 8 8l4.4-2.4L8 3.3ZM3 6.8v4l4.3 2.3v-4L3 6.8Zm10 0-4.3 2.3v4L13 10.8v-4Z"/>'
        "</svg>"
    ),
}

WORDS_PER_MINUTE = 200

# Hue range for the per-item "hotness" gradient — HSL hue rotates red (0) ->
# orange -> yellow -> green as it increases, so this pair alone produces the
# whole red-to-green path. See docs/technical-spec.md §14 (hotness gradient).
HOTTEST_HUE = 5
COOLEST_HUE = 125
HOT_SATURATION = "55%"

# Full-content stylesheet for a standalone site/issues/<iso-week>.html page
# — a design-critique pass found the homepage had no way to link a single
# issue on social media with its own title/description (a fragment link
# still shows the homepage's generic preview), so each issue now gets its
# own page. This constant duplicates the token/typography/brand rules also
# hand-authored in site/index.html's <style> — there's no build step in
# this project to share a stylesheet between a generated and a hand-authored
# page, so keep the two in sync by eye when either changes. The homepage
# itself now shows only a teaser per issue (see site/index.html's
# .teaser-* rules) — the rich per-item rendering (TOC, badges, icons) that
# used to live there moved here, unchanged in behavior.
ISSUE_PAGE_CSS = """
    :root{
      color-scheme: light dark;
      --bg: #f3f4ee; --ink: #1b241e; --ink-soft: #4b564d; --line: #d8dacd;
      --amber: #b8791e; --amber-ink: #1a1408;
      --hot-s: 62%; --hot-l: 38%; --surface-soft: #e9ebe2;
    }
    @media (prefers-color-scheme: dark){
      :root{
        --bg:#0e1410; --ink:#e9ede6; --ink-soft:#aeb8ac; --line:#2b342c;
        --amber:#e3a94b; --hot-l: 68%; --surface-soft: rgba(174,184,172,0.10);
      }
    }
    *{ box-sizing: border-box; }
    body{ margin: 0; background: var(--bg); color: var(--ink); font-family: Georgia, "Times New Roman", serif; line-height: 1.6; }
    main{ max-width: 640px; margin: 0 auto; padding: 3rem 1.5rem 6rem; }
    .brand{ display: flex; align-items: center; gap: 0.6rem; margin: 0 0 1.5rem; }
    .brand-mark{ width: 30px; height: 30px; flex: none; }
    .brand a{ font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; font-weight: 700; font-size: 1.1rem; color: var(--ink); text-decoration: none; }
    .brand a:hover{ color: var(--amber); }
    .back-link{ margin: 0 0 1.5rem; font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; font-size: 0.85rem; }
    .back-link a{ color: var(--ink-soft); text-decoration: none; }
    .back-link a:hover{ color: var(--amber); text-decoration: underline; }
    h1.issue-heading{ font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; font-size: 1.7rem; margin: 0 0 1rem; }
    .subscribe-cta{ margin: 2.5rem 0; }
    .subscribe-btn{
      display: inline-block; font-family: -apple-system, "Helvetica Neue", Arial, sans-serif;
      font-weight: 600; font-size: 0.9rem; color: var(--amber-ink);
      background: var(--amber); padding: 0.6rem 1.2rem; border-radius: 4px;
      text-decoration: none; letter-spacing: 0.01em;
    }
    .subscribe-btn:hover{ filter: brightness(1.08); }
    .issue-intro{ margin: 0 0 1.25rem; color: var(--ink); }
    .toc{
      display: flex; flex-direction: column; gap: 0.9rem;
      margin: 0 0 1.5rem; padding: 1rem 1.1rem; border: 1px solid var(--line); border-radius: 8px;
    }
    .toc-group{ border-left: 3px solid hsl(var(--hot-hue) var(--hot-s) var(--hot-l)); padding-left: 0.75rem; }
    .toc-group h4{
      font-family: -apple-system, "Helvetica Neue", Arial, sans-serif;
      font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em;
      color: hsl(var(--hot-hue) var(--hot-s) var(--hot-l)); margin: 0 0 0.4rem;
    }
    .toc-group .count{ font-weight: 400; opacity: 0.7; }
    .toc-group ul{ list-style: none; margin: 0; padding: 0; }
    .toc-group li{ display: flex; align-items: baseline; gap: 0.4rem; font-size: 0.88rem; margin: 0 0 0.25rem; }
    .toc-group .dot{ width: 0.4rem; height: 0.4rem; border-radius: 50%; flex: none; background: hsl(var(--hot-hue) var(--hot-s) var(--hot-l)); }
    .toc-group a{ color: var(--ink); text-decoration: none; }
    .toc-group a:hover{ color: var(--amber); text-decoration: underline; }
    .issue-items{ list-style: none; padding: 0; margin: 0; }
    .issue-item{
      padding: 1.1rem 0 1.1rem 0.9rem; border-top: 1px solid var(--line);
      border-left: 3px solid hsl(var(--hot-hue) var(--hot-s) var(--hot-l));
    }
    .issue-item:first-child{ border-top: none; padding-top: 0; }
    .issue-item h4{ font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; font-size: 1.08rem; font-weight: 700; margin: 0 0 0.3rem; }
    .issue-item h4 a{ color: hsl(var(--hot-hue) var(--hot-s) var(--hot-l)); text-decoration: none; }
    .issue-item h4 a:hover{ text-decoration: underline; }
    .item-source-title{ font-size: 0.82rem; color: var(--ink-soft); margin: 0 0 0.7rem; font-style: italic; }
    .badge-row{ display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem; margin: 0 0 0.6rem; }
    .franchise-tag, .category-badge, .read-time{
      display: inline-flex; align-items: center; gap: 0.32rem;
      font-family: -apple-system, "Helvetica Neue", Arial, sans-serif;
      font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.06em;
      border-radius: 3px; padding: 0.14rem 0.45rem;
    }
    .franchise-tag{ color: var(--amber); border: 1px solid var(--amber); }
    .category-badge{ font-weight: 700; color: hsl(var(--hot-hue) var(--hot-s) var(--hot-l)); background: hsl(var(--hot-hue) var(--hot-s) var(--hot-l) / 15%); }
    .category-icon{ width: 0.7rem; height: 0.7rem; flex: none; color: currentColor; }
    .read-time{ color: var(--ink-soft); background: var(--surface-soft); font-weight: 600; }
    .issue-item details{ margin: 0 0 0.6rem; }
    .issue-item summary{ cursor: pointer; font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; font-size: 0.8rem; color: var(--ink-soft); }
    .issue-item summary:hover{ color: var(--ink); }
    .issue-item details[open] summary{ margin-bottom: 0.4rem; }
    .issue-item blockquote{ margin: 0; padding-left: 0.75rem; border-left: 2px solid var(--line); color: var(--ink-soft); font-style: italic; font-size: 0.92rem; }
    .issue-item p{ margin: 0 0 0.5rem; }
    .issue-item p:last-child{ margin-bottom: 0; }
    .primary-source{ font-size: 0.85rem; color: var(--ink-soft); }
    .primary-source a{ color: inherit; }
    footer{ margin-top: 3rem; font-size: 0.85rem; color: var(--ink-soft); }
    footer a{ color: inherit; }
"""

# The approved brand mark (radar sweep held inside monitoring brackets — see
# the project's design exploration), reused verbatim on every standalone
# issue page. Matches the copy hand-authored in site/index.html's masthead.
BRAND_MARK_SVG = """<svg class="brand-mark" viewBox="0 0 100 100" role="img" aria-hidden="true">
        <g stroke="var(--ink-soft)" stroke-width="3.6" stroke-linecap="round" fill="none">
          <path d="M17 30V19a2 2 0 0 1 2-2h11"/>
          <path d="M83 30V19a2 2 0 0 1-2-2H70"/>
          <path d="M17 70v11a2 2 0 0 0 2 2h11"/>
          <path d="M83 70v11a2 2 0 0 1-2 2H70"/>
        </g>
        <circle cx="50" cy="50" r="24" fill="none" stroke="var(--ink-soft)" stroke-opacity="0.4" stroke-width="1.8"/>
        <circle cx="50" cy="50" r="15.5" fill="none" stroke="var(--ink-soft)" stroke-opacity="0.4" stroke-width="1.4"/>
        <line x1="26" y1="50" x2="74" y2="50" stroke="var(--ink-soft)" stroke-opacity="0.35" stroke-width="1"/>
        <line x1="50" y1="26" x2="50" y2="74" stroke="var(--ink-soft)" stroke-opacity="0.35" stroke-width="1"/>
        <path d="M50 50 L66.97 33.03 L70.24 37.10 Z" fill="hsl(5 62% var(--hot-l))" opacity="0.85"/>
        <path d="M50 50 L70.24 37.10 L72.55 41.79 Z" fill="hsl(20 62% var(--hot-l))" opacity="0.72"/>
        <path d="M50 50 L72.55 41.79 L73.79 46.87 Z" fill="hsl(35 62% var(--hot-l))" opacity="0.60"/>
        <path d="M50 50 L73.79 46.87 L73.91 52.09 Z" fill="hsl(50 60% var(--hot-l))" opacity="0.48"/>
        <path d="M50 50 L73.91 52.09 L72.89 57.22 Z" fill="hsl(65 55% var(--hot-l))" opacity="0.36"/>
        <path d="M50 50 L72.89 57.22 L70.78 62.00 Z" fill="hsl(80 50% var(--hot-l))" opacity="0.25"/>
        <path d="M50 50 L70.78 62.00 L67.70 66.21 Z" fill="hsl(95 48% var(--hot-l))" opacity="0.15"/>
        <path d="M50 50 L67.70 66.21 L63.77 69.66 Z" fill="hsl(110 45% var(--hot-l))" opacity="0.07"/>
        <line x1="50" y1="50" x2="66.97" y2="33.03" stroke="hsl(5 70% var(--hot-l))" stroke-width="2.2" stroke-linecap="round"/>
        <circle cx="66.97" cy="33.03" r="3.4" fill="var(--amber)"/>
        <circle cx="50" cy="50" r="2.4" fill="var(--ink)"/>
      </svg>"""


def _item_anchor(cluster_id: str) -> str:
    return f"item-{cluster_id}"


def _hotness_order(draft: list[dict], ranked_by_cluster: dict) -> list[tuple[dict, int]]:
    """Returns (entry, hue) pairs sorted hottest to coolest.

    Direct user request: a true gradient, not 4 fixed swatches — item order
    and color should both reflect it, "best hook to less-best hook." A
    category alone (see CATEGORY_ORDER) is too coarse for that, and asking
    the drafting step to hand-assign a numeric hotness to every item would
    add subjective, hard-to-calibrate busywork to every future issue. So
    category sets the coarse band (unchanged from the earlier hottest-to-
    coldest ordering — still the dominant, editorially-judged signal) and
    each item's real cluster_score (already computed by pipeline.score,
    already used to rank it into data/ranked/<iso-week>.json — nothing new
    drafted) places it within that band, hottest-scoring item first. This
    also means field_notes items are no longer hard-coded to one neutral
    color — they fall wherever their band naturally lands on the same
    gradient as everything else.
    """
    hue_band_rank = {c: i for i, c in enumerate(HUE_BAND_ORDER)}
    n_categories = len(CATEGORY_ORDER)
    band_width = (COOLEST_HUE - HOTTEST_HUE) / n_categories

    groups: dict[str, list[dict]] = {c: [] for c in CATEGORY_ORDER}
    for entry in draft:
        category = entry.get("category", "new_product")
        groups.setdefault(category, []).append(entry)

    ordered: list[tuple[dict, int]] = []
    for category in CATEGORY_ORDER:
        items = groups.get(category, [])
        if not items:
            continue
        items = sorted(
            items,
            key=lambda e: ranked_by_cluster.get(e["cluster_id"], {}).get("cluster_score", 0),
            reverse=True,
        )
        rank = hue_band_rank[category]
        band_start = HOTTEST_HUE + band_width * rank
        group_size = len(items)
        for i, entry in enumerate(items):
            # i=0 (hottest-scoring item in this category) sits at the band's
            # hot edge; the coolest sits just short of the next band's start.
            local_fraction = i / group_size
            hue = round(band_start + band_width * local_fraction)
            ordered.append((entry, hue))

    # Any category not in CATEGORY_ORDER (shouldn't happen with a valid
    # draft, but not verify.py-enforced — see draft-schema.md) sorts last,
    # coolest hue, rather than silently vanishing from the issue.
    unknown = [e for e in draft if e.get("category", "new_product") not in hue_band_rank]
    for entry in unknown:
        ordered.append((entry, COOLEST_HUE))

    return ordered


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


_SOURCE_POST_PREFIX_RE = re.compile(r"^(?:Show HN|Ask HN|Tell HN)\s*:\s*", re.IGNORECASE)


def _clean_display_title(title: str) -> str:
    """Strips source-platform metadata prefixes for display.

    A design-critique pass flagged that item titles were rendered verbatim
    from the source (e.g. "Show HN: ..."), which reads as "this was
    scraped" rather than "our editors picked this." `Show HN:`/`Ask HN:`/
    `Tell HN:` are HN's own submission-type metadata, not part of the
    author's actual title, so they're stripped for display only — the
    underlying `entry["title"]` used for citation matching is untouched.
    """
    return _SOURCE_POST_PREFIX_RE.sub("", title or "").strip()


def _is_http_url(url: str) -> bool:
    return bool(url) and urlsplit(url).scheme in ("http", "https")


def _load_draft(draft_path: str) -> tuple[str, str, list[dict]]:
    """Returns (subject, intro, items). See digest-draft-schema §12.2.

    `subject` is the line that goes in the email platform's subject field —
    added after a design-critique pass found no field anywhere in the
    pipeline produced one, leaving it improvised at send time, disconnected
    from drafting/verification. Not rendered into site/index.html (a
    subject line is an email-only concept); surfaced at the top of
    digest/<iso-week>.md instead, clearly labeled, so the human doing the
    manual paste-and-send step (see docs/weekly-runbook.md) can copy it
    straight into Beehiiv. Optional in code (older drafts won't have it)
    but treated as required practice by the draft-digest skill.

    `intro` is a short connective narrative for the whole issue — dry wit,
    still professional (see docs/editorial-guidelines.md) — written once
    per issue, not per item. Added after real user feedback on the first
    live issue: three isolated per-item summaries with no frame or
    synthesis read as a bare link list, not a newsletter. Optional — an
    empty string is valid and renders nothing, so a thin week doesn't force
    a forced-sounding intro.
    """
    data = read_json(draft_path)
    return data.get("subject", ""), data.get("intro", ""), data.get("items", [])


# (singular, plural) phrasing per category for _teaser_summary_line below.
_CATEGORY_STAT_WORDS = {
    "breaking": ("breaking", "breaking"),
    "new_product": ("new product", "new products"),
    "notable": ("notable", "notable"),
    "field_notes": ("field note", "field notes"),
}


def _teaser_summary_line(draft: list[dict], ranked_by_cluster: dict) -> str:
    """"N items across N sources — N breaking, N new products, ..." — the
    at-a-glance summary shown on the homepage's teaser card for this issue,
    and again at the top of the issue's own standalone page.

    This is the old per-issue "In this issue" stats line, cut earlier in
    the design-critique pass because it duplicated the table of contents
    one scroll below it on the same page. It's back here in a genuinely
    different role: a homepage teaser has no TOC to duplicate — this line
    *is* the at-a-glance summary a reader scanning the archive needs before
    clicking through, so it earns its place again in this new spot.
    """
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
    summary = f"{len(draft)} {item_word} across {len(sources)} {source_word}"
    if parts:
        summary += " — " + ", ".join(parts)
    return summary + "."


def _meta_description(subject: str, intro: str, iso_week: str) -> str:
    """Best available one-line description for an issue's <meta
    description>/og:description/twitter:description — subject first (it's
    already written to be a single punchy sentence), falling back to a
    truncated intro, falling back to a generic line so a description is
    never empty (an empty og:description makes for a broken-looking social
    preview card).
    """
    text = subject or intro
    if not text:
        return f"Guardrail Radar — the {iso_week} issue."
    return text if len(text) <= 200 else text[:197].rstrip() + "…"


def _render_issue_page_html(
    iso_week: str,
    subject: str,
    intro: str,
    intro_html: str,
    toc_html: str,
    items_html: str,
) -> str:
    """A standalone, fully self-contained page for one issue — added after
    a direct user request for issues linkable on social media. Before this,
    the only way to reference a past issue was the homepage itself, which
    has no per-issue title/description, so a shared link always produced
    the same generic homepage preview card regardless of which issue was
    meant. Each page gets its own <title>, canonical url, and Open
    Graph/Twitter Card tags — subject (already written as one punchy,
    specific sentence for the Beehiiv send) doubles as the social
    description via _meta_description, falling back to the plain-text
    `intro` (not `intro_html`, which is already wrapped/escaped for body
    rendering and not reusable as attribute content).

    No "In this issue: N items..." summary line here, unlike the homepage
    teaser (_render_homepage_teaser_html) — the table of contents right
    below already conveys that, with links; repeating it here would be
    exactly the same redundancy the design-critique pass cut in the first
    place, just relocated rather than actually fixed.
    """
    page_title = f"Guardrail Radar — {iso_week}"
    description = html.escape(_meta_description(subject, intro, iso_week), quote=True)
    page_url = f"{SITE_BASE_URL}/issues/{iso_week}.html"
    og_image = f"{SITE_BASE_URL}/og-image.png"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(page_title)}</title>
  <meta name="description" content="{description}">
  <link rel="canonical" href="{html.escape(page_url, quote=True)}">
  <link rel="icon" type="image/svg+xml" href="../favicon.svg">
  <meta property="og:type" content="article">
  <meta property="og:title" content="{html.escape(page_title, quote=True)}">
  <meta property="og:description" content="{description}">
  <meta property="og:url" content="{html.escape(page_url, quote=True)}">
  <meta property="og:image" content="{html.escape(og_image, quote=True)}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{html.escape(page_title, quote=True)}">
  <meta name="twitter:description" content="{description}">
  <meta name="twitter:image" content="{html.escape(og_image, quote=True)}">
  <style>{ISSUE_PAGE_CSS}</style>
</head>
<body>
  <main>
    <div class="brand">
      {BRAND_MARK_SVG}
      <a href="../index.html">Guardrail Radar</a>
    </div>
    <p class="back-link"><a href="../index.html">← All issues</a></p>
    <h1 class="issue-heading">{html.escape(iso_week)}</h1>
    {intro_html}
    {toc_html}
    <ul class="issue-items">{items_html}</ul>
    <!-- Subscribe CTA — styled and ready, left commented out rather than
         pointing at a guessed or fabricated URL: no Beehiiv publication
         exists yet (see docs/project-plan.md §11). Uncomment and set the
         real href once the account is live.
    <p class="subscribe-cta"><a class="subscribe-btn" href="https://REPLACE-WITH-REAL-BEEHIIV-URL">Subscribe for the weekly issue →</a></p>
    -->
    <footer>
      <p><a href="../index.html">← Back to all issues</a></p>
    </footer>
  </main>
</body>
</html>
"""


def _render_homepage_teaser_html(iso_week: str, subject: str, intro: str, summary_line: str) -> str:
    """The homepage archive's per-issue entry — a short teaser linking to
    that issue's own standalone page, added alongside it. Previously this
    was the issue's *entire* content, inline; kept short here so the
    homepage stays scannable as issues accumulate, and because the full
    content now has a better home (see _render_issue_page_html) that's
    actually linkable on its own.
    """
    description = html.escape(_meta_description(subject, intro, iso_week))
    issue_href = f"issues/{iso_week}.html"
    return (
        f'<h3 class="week-heading"><a href="{issue_href}">{html.escape(iso_week)}</a></h3>'
        f'<p class="teaser-desc">{description}</p>'
        f'<p class="teaser-stats">{html.escape(summary_line)}</p>'
        f'<a class="teaser-link" href="{issue_href}">Read the full issue →</a>'
    )


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


def render_final_digest(iso_week: str) -> tuple[str, str, str]:
    draft_path = os.path.join("digest", "draft", f"{iso_week}.json")
    ranked_path = os.path.join("data", "ranked", f"{iso_week}.json")
    verification_path = os.path.join("digest", "verification", f"{iso_week}.json")

    subject, intro, draft = _load_draft(draft_path)
    ranked_by_cluster = {c["cluster_id"]: c for c in read_json(ranked_path)}

    # Reorder items hottest-to-coldest before anything renders, so the
    # actual reading order in digest/<week>.md and site/index.html matches
    # the table of contents instead of just the TOC reflecting it while the
    # body stays in whatever order the draft happened to list items in. See
    # _hotness_order's docstring for how the gradient itself is computed.
    hotness = _hotness_order(draft, ranked_by_cluster)
    draft = [entry for entry, _hue in hotness]
    hue_by_cluster_id = {entry["cluster_id"]: hue for entry, hue in hotness}
    summary_line = _teaser_summary_line(draft, ranked_by_cluster)

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

    lines_md = []

    # Subject line — the text that goes in Beehiiv's subject field, not
    # part of the issue body. Rendered as its own clearly-labeled line at
    # the very top of digest/<iso-week>.md, above the H1, so the human
    # doing the manual paste-and-send step (docs/weekly-runbook.md) can
    # copy it straight into the platform's subject field before pasting
    # everything below into the body. Not rendered on site/index.html — a
    # subject line is an email-only concept, not part of the public archive.
    if subject:
        lines_md.append(f"**Subject line (paste into Beehiiv, not part of the issue body):** {_md_escape(subject)}")
        lines_md.append("")

    lines_md.append(f"# Guardrail Radar — {iso_week}")
    lines_md.append("")

    # The redundant "In this issue: N items across N sources — ..." stats
    # line was cut after a design-critique pass found it repeated, almost
    # verbatim, information the table of contents below already conveys
    # better (with working links, right after it).
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
        # The TOC links with the same text used as each item's own headline
        # below (hook first, cleaned title as fallback) — a design-critique
        # pass found the page taught readers two different labels for the
        # same item (a raw scraped title in the TOC, a hand-written hook in
        # the body), and had the raw title doing the headline's job in both
        # places even though the hook is the actually-written pitch.
        toc_text = entry.get("hook") or _clean_display_title(title)
        toc_groups.setdefault(category, []).append((toc_text, entry["cluster_id"]))

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

        # Each link gets a dot in that item's own hue (draft is already
        # sorted hottest-first within the category, so the dots visibly
        # cool down top-to-bottom within a group, not just group-to-group).
        toc_links = "".join(
            f'<li style="--hot-hue:{hue_by_cluster_id[cid]}">'
            f'<span class="dot"></span><a href="#{_item_anchor(cid)}">{html.escape(title)}</a></li>'
            for title, cid in items
        )
        # The group heading/left-border uses its hottest item's hue (items
        # are sorted hottest-first within the category), so the TOC and the
        # items below it read as one continuous gradient, not a fixed
        # per-category color plus a separate per-item one.
        group_hue = hue_by_cluster_id[items[0][1]]
        toc_html_parts.append(
            f'<div class="toc-group" style="--hot-hue:{group_hue}"><h4>{html.escape(label)} '
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
        hue = hue_by_cluster_id[entry["cluster_id"]]
        read_minutes = _read_time_minutes(hook, excerpt, note)
        display_title = _clean_display_title(title)

        # Headline hierarchy flip, per a design-critique pass: every item
        # used to lead with its raw scraped source title (jargon-dense,
        # often carrying platform metadata like "Show HN:") and demote the
        # hand-written hook — the actual reason to care — to a bold line
        # underneath. The hook now IS the headline; the cleaned source
        # title becomes a small secondary caption, present only when a
        # hook exists to be secondary to (older/hookless entries keep the
        # title as the headline, unchanged).
        headline_text = hook or display_title
        if url:
            lines_md.append(f"### [{_md_escape(headline_text)}]({url})")
        else:
            lines_md.append(f"### {_md_escape(headline_text)}")
        if hook:
            lines_md.append(f"_{_md_escape(display_title)}_")
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
        lines_md.append("")
        lines_md.append(note)
        # Excerpt moved after the note, not between the hook and the note —
        # a design-critique pass found the old placement broke the
        # hook-to-note reading flow for what's supporting evidence, not the
        # main copy.
        if excerpt:
            lines_md.append("")
            lines_md.append(f"> {_md_escape(excerpt)}")
        if entry.get("primary_source_url"):
            lines_md.append(f"\nPrimary source: {_md_escape(entry['primary_source_url'])}")
        lines_md.append("")

        archive_items_html.append(
            _render_archive_item_html(
                entry["cluster_id"], display_title, url, hook, excerpt, note, franchise, category, hue, read_minutes, entry
            )
        )

    digest_md = "\n".join(lines_md)
    digest_path = os.path.join("digest", f"{iso_week}.md")
    with open(digest_path, "w", encoding="utf-8") as f:
        f.write(digest_md)

    # Standalone, linkable page for this one issue — added after a direct
    # user request for past issues that can be shared on social media with
    # their own title/description, not just the homepage's generic preview.
    issue_page_path = os.path.join("site", "issues", f"{iso_week}.html")
    os.makedirs(os.path.dirname(issue_page_path), exist_ok=True)
    with open(issue_page_path, "w", encoding="utf-8") as f:
        f.write(
            _render_issue_page_html(
                iso_week, subject, intro, intro_html, toc_html, "".join(archive_items_html)
            )
        )

    teaser_html = _render_homepage_teaser_html(iso_week, subject, intro, summary_line)
    site_path = _update_site_archive(iso_week, teaser_html)
    return digest_path, site_path, issue_page_path


def _render_archive_item_html(
    cluster_id: str,
    title: str,
    url: str,
    hook: str,
    excerpt: str,
    note: str,
    franchise: str,
    category: str,
    hue: int,
    read_minutes: int,
    entry: dict,
) -> str:
    """One item's full content for the site — headline, hook, badges, note,
    excerpt, franchise label, primary source. Previously this rendered only
    a bare linked title, dropping the actual commentary (the entire point
    of the newsletter) from the one place the public site shows it — the
    full text still went into digest/<week>.md, just never into
    site/index.html, despite docs/technical-spec.md §14 saying the site
    gets "the same content." Found by the user looking at the real
    deployed site.

    `title` here is already display-cleaned (source-platform prefixes like
    "Show HN:" stripped — see _clean_display_title) by the caller.

    Headline is `hook`, not `title` — a design-critique pass found every
    item leading with its raw scraped source title (jargon-dense, often
    carrying platform metadata) while the hand-written hook, the actual
    reason to care, rendered as a subordinate line underneath. The hook is
    now the <h4>; the cleaned title becomes a small secondary caption,
    shown only when there's a hook for it to be secondary to (an entry with
    no hook falls back to the title as its own headline, unchanged).

    The returned <li> carries a stable id="item-<cluster_id>" so the
    table-of-contents nav built in render_final_digest can link straight
    to it.

    badge-row (franchise tag + category badge + read-time) was added after
    a format audit against comparable newsletters (TLDR, tl;dr sec, The
    Batch) — category is meant to register before a reader parses the
    headline. Each category badge also carries a small inline-SVG icon
    (CATEGORY_ICON_SVG) — added after a design-critique pass found the page
    was pure text with zero visual texture anywhere.

    The <details>-collapsed excerpt now renders *after* the note, not
    between the hook and the note — a design-critique pass found the old
    placement broke the hook-to-note reading flow for what's supporting
    evidence, not the main copy. The collapse is site-only: <details> can't
    be relied on to survive a paste into Beehiiv, so digest/<week>.md keeps
    the excerpt always visible (also after the note, for the same reason).

    Color is a continuous per-item gradient (red -> orange -> yellow ->
    green), not fixed category swatches — see _hotness_order for how the
    hue itself is computed, and HUE_BAND_ORDER (separate from CATEGORY_ORDER)
    for which category owns which end of it. `hue` (0-360, computed there)
    drives every colored element here via the CSS custom property
    --hot-hue, set once on the outer <li> and inherited by the badge, dot,
    icon, and headline color — one continuous system instead of a
    category-keyed one.
    """
    headline_text = hook or title
    heading = f'<a href="{html.escape(url)}">{html.escape(headline_text)}</a>' if url else html.escape(headline_text)
    parts = [f"<h4>{heading}</h4>"]
    if hook:
        parts.append(f'<p class="item-source-title">{html.escape(title)}</p>')

    badges = []
    if franchise and franchise != "weekly":
        label = html.escape(franchise.replace("_", " ").title())
        badges.append(f'<span class="franchise-tag">{label}</span>')
    category_label = html.escape(CATEGORY_BADGE_LABELS.get(category, category))
    category_icon = CATEGORY_ICON_SVG.get(category, "")
    badges.append(f'<span class="category-badge">{category_icon}{category_label}</span>')
    badges.append(f'<span class="read-time">{read_minutes} min read</span>')
    parts.append(f'<div class="badge-row">{"".join(badges)}</div>')

    if note:
        parts.append(f"<p>{html.escape(note)}</p>")

    if excerpt:
        parts.append(
            "<details><summary>Read the source excerpt</summary>"
            f"<blockquote>{html.escape(excerpt)}</blockquote></details>"
        )

    primary = entry.get("primary_source_url")
    if primary and _is_http_url(primary):
        parts.append(
            f'<p class="primary-source">Primary source: '
            f'<a href="{html.escape(primary)}">{html.escape(primary)}</a></p>'
        )

    anchor = html.escape(_item_anchor(cluster_id), quote=True)
    return f'<li class="issue-item" id="{anchor}" style="--hot-hue:{hue}">{"".join(parts)}</li>'


def _update_site_archive(iso_week: str, teaser_html: str) -> str:
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

    `teaser_html` (from `_render_homepage_teaser_html`) is a short summary
    linking to that issue's own standalone page — see
    `_render_issue_page_html` — which now carries the full content this
    function used to embed directly.
    """
    site_path = os.path.join("site", "index.html")
    with open(site_path, encoding="utf-8") as f:
        html_text = f.read()

    week_attr = html.escape(iso_week, quote=True)
    start_marker = f"<!-- week:{week_attr} -->"
    end_marker = f"<!-- /week:{week_attr} -->"
    week_block = f'{start_marker}<li data-week="{week_attr}">{teaser_html}</li>{end_marker}'

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
        digest_path, site_path, issue_page_path = render_final_digest(iso_week)
        print(f"[render] wrote {digest_path}, {issue_page_path}, and updated {site_path}")


if __name__ == "__main__":
    main()
