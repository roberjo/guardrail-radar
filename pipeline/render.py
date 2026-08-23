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
    intro_html = ""
    if intro:
        lines_md.append(intro)
        lines_md.append("")
        intro_html = f"<p class=\"issue-intro\">{html.escape(intro)}</p>"
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

        if url:
            lines_md.append(f"### [{_md_escape(title)}]({url})")
        else:
            lines_md.append(f"### {_md_escape(title)}")
        if franchise != "weekly":
            lines_md.append(f"_{franchise.replace('_', ' ').title()}_")
        if hook:
            lines_md.append(f"**{_md_escape(hook)}**")
        if excerpt:
            lines_md.append(f"> {_md_escape(excerpt)}")
        lines_md.append("")
        lines_md.append(note)
        if entry.get("primary_source_url"):
            lines_md.append(f"\nPrimary source: {_md_escape(entry['primary_source_url'])}")
        lines_md.append("")

        archive_items_html.append(_render_archive_item_html(title, url, hook, excerpt, note, franchise, entry))

    digest_md = "\n".join(lines_md)
    digest_path = os.path.join("digest", f"{iso_week}.md")
    with open(digest_path, "w", encoding="utf-8") as f:
        f.write(digest_md)

    site_path = _update_site_archive(iso_week, archive_items_html, intro_html)
    return digest_path, site_path


def _render_archive_item_html(
    title: str, url: str, hook: str, excerpt: str, note: str, franchise: str, entry: dict
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
    """
    heading = f'<a href="{html.escape(url)}">{html.escape(title)}</a>' if url else html.escape(title)
    parts = [f"<h4>{heading}</h4>"]

    if franchise and franchise != "weekly":
        label = html.escape(franchise.replace("_", " ").title())
        parts.append(f'<span class="franchise-tag">{label}</span>')

    if hook:
        parts.append(f'<p class="item-hook">{html.escape(hook)}</p>')

    if excerpt:
        parts.append(f"<blockquote>{html.escape(excerpt)}</blockquote>")

    if note:
        parts.append(f"<p>{html.escape(note)}</p>")

    primary = entry.get("primary_source_url")
    if primary and _is_http_url(primary):
        parts.append(
            f'<p class="primary-source">Primary source: '
            f'<a href="{html.escape(primary)}">{html.escape(primary)}</a></p>'
        )

    return f'<li class="issue-item">{"".join(parts)}</li>'


def _update_site_archive(iso_week: str, item_html_list: list[str], intro_html: str = "") -> str:
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
        + intro_html
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
