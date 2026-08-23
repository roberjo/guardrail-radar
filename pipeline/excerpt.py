"""Excerpt capture — see docs/technical-spec.md §6.

Fetches real source text so the drafting step never has to write commentary
from a bare title. Security note: this fetches arbitrary third-party URLs
(from Reddit/HN/GitHub items), so it is deliberately defensive — restricted
to http(s), and refuses to fetch a URL that resolves to a private, loopback,
or link-local address (basic SSRF hardening for a script that runs
unattended in CI).
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

MAX_EXCERPT_CHARS = 1000
FETCH_TIMEOUT = 5
USER_AGENT = (
    "guardrail-radar-bot/1.0 "
    "(excerpt capture for a curated newsletter; see project repo for contact)"
)


def _is_safe_host(hostname: str) -> bool:
    """Best-effort SSRF guard: reject hosts resolving to non-public addresses."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for _family, _type, _proto, _canon, sockaddr in infos:
        try:
            addr = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return False
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast:
            return False
    return True


def _meta_content(tag: Tag | NavigableString | None) -> str | None:
    """Extract and strip a <meta content="..."> value, or None if unusable.

    A bare `tag.get("content", "").strip()` doesn't type-check cleanly:
    BeautifulSoup's `.find()` can return a NavigableString (no `.get()`),
    and an attribute value can technically be a list (multi-valued attrs).
    Neither happens for a real <meta> tag's content attribute, but this
    narrows explicitly rather than assuming it.
    """
    if not isinstance(tag, Tag):
        return None
    content = tag.get("content")
    if not isinstance(content, str):
        return None
    content = content.strip()
    return content or None


def _fetch_primary(url: str, session: requests.Session | None = None) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None
    if not parts.hostname or not _is_safe_host(parts.hostname):
        return None

    getter = session.get if session is not None else requests.get
    try:
        resp = getter(
            url,
            timeout=FETCH_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return None

    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    og_text = _meta_content(soup.find("meta", attrs={"property": "og:description"}))
    if og_text:
        return og_text

    meta_text = _meta_content(soup.find("meta", attrs={"name": "description"}))
    if meta_text:
        return meta_text

    for p in soup.find_all("p"):
        # separator=" " matters: without it, "a <i>real</i> comment" collapses
        # to "arealcomment" — found via a failing test, not spec guesswork.
        text = p.get_text(" ", strip=True)
        if len(text) > 40:
            return text

    return None


def capture_excerpt(
    url: str, fallback_text: str = "", session: requests.Session | None = None
) -> tuple[str, str]:
    """Return (excerpt, excerpt_status) per docs/technical-spec.md §6."""
    primary = _fetch_primary(url, session=session)
    if primary:
        return primary[:MAX_EXCERPT_CHARS], "ok"
    cleaned_fallback = (fallback_text or "").strip()
    if cleaned_fallback:
        # HN's Algolia API returns story_text as raw HTML — literal <p> tags
        # and entity-encoded characters (HN encodes "/" as "&#x2F;" in its
        # own stored text), not plain text. Left as-is, those entities
        # survive verbatim into the excerpt, and pipeline.render's
        # html.escape() then double-escapes the leading "&" into "&amp;",
        # so a reader sees the literal string "&#x2F;" instead of "/" —
        # found live on the site, not in a test. hn_comment_fallback below
        # already strips this correctly via BeautifulSoup.get_text(); this
        # path didn't. Other connectors' fallback_text is already plain
        # text, so running it through the same stripping is a safe no-op
        # for them (get_text on tag-free text just normalizes whitespace).
        cleaned_fallback = BeautifulSoup(cleaned_fallback, "html.parser").get_text(" ", strip=True)
    if cleaned_fallback:
        return cleaned_fallback[:MAX_EXCERPT_CHARS], "partial"
    return "", "none"


def hn_comment_fallback(object_id: str, session: requests.Session | None = None) -> str:
    """Top-level comment text for an HN item with no story_text of its own (§6)."""
    getter = session.get if session is not None else requests.get
    try:
        resp = getter(
            f"https://hn.algolia.com/api/v1/items/{object_id}",
            timeout=FETCH_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return ""

    for child in data.get("children", []) or []:
        text = child.get("text")
        if text:
            return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    return ""
