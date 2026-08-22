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

    draft = read_json(draft_path)
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
    archive_items_html = []

    for entry in draft:
        cluster = ranked_by_cluster.get(entry["cluster_id"], {})
        title = entry.get("title") or cluster.get("title", "(untitled)")
        url = entry.get("url") or cluster.get("url", "")
        if not _is_http_url(url):
            print(f"[render] WARNING: entry {entry['cluster_id']!r} has no safe http(s) url — rendering title only, no link", file=sys.stderr)
            url = ""
        excerpt = cluster.get("cluster_excerpt", "")
        note = entry.get("note", "")
        franchise = entry.get("franchise", "weekly")

        if url:
            lines_md.append(f"### [{_md_escape(title)}]({url})")
        else:
            lines_md.append(f"### {_md_escape(title)}")
        if franchise != "weekly":
            lines_md.append(f"_{franchise.replace('_', ' ').title()}_")
        if excerpt:
            lines_md.append(f"> {_md_escape(excerpt)}")
        lines_md.append("")
        lines_md.append(note)
        if entry.get("primary_source_url"):
            lines_md.append(f"\nPrimary source: {_md_escape(entry['primary_source_url'])}")
        lines_md.append("")

        if url:
            archive_items_html.append(f'<li><a href="{html.escape(url)}">{html.escape(title)}</a></li>')
        else:
            archive_items_html.append(f"<li>{html.escape(title)}</li>")

    digest_md = "\n".join(lines_md)
    digest_path = os.path.join("digest", f"{iso_week}.md")
    with open(digest_path, "w", encoding="utf-8") as f:
        f.write(digest_md)

    site_path = _update_site_archive(iso_week, archive_items_html)
    return digest_path, site_path


def _update_site_archive(iso_week: str, item_html_list: list[str]) -> str:
    """Insert/replace this week's archive entry — idempotent on re-run.

    Re-running weekly-verify-and-publish for a week that already has an
    archive entry (e.g. to fix a typo and re-render) used to append a
    second <li> instead of replacing the first — found by the reviewer
    agent via an actual reproduction, not a hypothetical. Each entry now
    carries a data-week attribute so a re-run finds and replaces its own
    prior entry instead of duplicating it.
    """
    site_path = os.path.join("site", "index.html")
    with open(site_path, encoding="utf-8") as f:
        html_text = f.read()

    week_attr = html.escape(iso_week, quote=True)
    week_block = (
        f'<li data-week="{week_attr}"><strong>{html.escape(iso_week)}</strong><ul>'
        + "".join(item_html_list)
        + "</ul></li>"
    )

    # Terminate on the literal `</ul></li>` sequence, not a bare `</li>` —
    # the block contains nested per-story <li> elements, and a bare `.*?</li>`
    # matches the FIRST inner one, truncating the replacement and leaving a
    # stray `</ul></li>` behind. Confirmed by reproducing it: the first fix
    # attempt passed the "no duplicate entry" check but still corrupted the
    # HTML on a second render.
    existing_pattern = re.compile(
        rf'<li data-week="{re.escape(week_attr)}">.*?</ul></li>', re.DOTALL
    )
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
