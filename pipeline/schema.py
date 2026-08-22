"""Normalized item schema shared by all connectors — see docs/technical-spec.md §5."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

VALID_SOURCES = {"hn", "reddit", "github", "lobsters", "producthunt"}
VALID_EXCERPT_STATUS = {"ok", "partial", "none"}

# Common tracking params stripped during canonicalization (§5). Not
# exhaustive by design — this is a cheap first pass, not a privacy tool.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "ref_src", "fbclid", "gclid", "mc_cid", "mc_eid", "igshid",
}


def canonicalize_url(url: str) -> str:
    """Strip tracking params and lowercase the host, per docs/technical-spec.md §5."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    query = urlencode(query_pairs)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), host, path, query, ""))


def item_id(normalized_url: str) -> str:
    """sha256(normalized_url) — the dedup key across sources (§5, §9)."""
    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()


@dataclass
class NormalizedItem:
    source: str
    title: str
    url: str
    raw_score: int
    comment_count: int
    posted_at: str  # ISO8601 UTC
    fetched_at: str  # ISO8601 UTC
    excerpt: str = ""
    excerpt_status: str = "none"
    source_meta: dict = field(default_factory=dict)
    id: str = ""

    def __post_init__(self) -> None:
        if self.source not in VALID_SOURCES:
            raise ValueError(f"unknown source: {self.source!r}")
        if self.excerpt_status not in VALID_EXCERPT_STATUS:
            raise ValueError(f"invalid excerpt_status: {self.excerpt_status!r}")
        if not self.url:
            raise ValueError("url is required")
        self.url = canonicalize_url(self.url)
        if not self.id:
            self.id = item_id(self.url)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> NormalizedItem:
        return cls(**data)
