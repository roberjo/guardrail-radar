"""Verification — see docs/technical-spec.md §13.

Gates digest/draft/<iso-week>.json before it can be rendered into a final
digest: link resolution, citation cross-check against data/ranked, a
claims-ledger fuzzy-match diff, and a hard primary-source requirement for
vendor_watch/policy_corner entries. Annotates only — never edits the draft.
"""

from __future__ import annotations

import argparse
import difflib
import ipaddress
import os
import re
import socket
import sys
from urllib.parse import urlsplit

import requests

from pipeline.io_utils import iso_week_str, read_json, write_json

REQUEST_TIMEOUT = 10
CLAIM_MATCH_THRESHOLD = 0.5
# supported_by is supposed to be a near-verbatim excerpt quote, not a
# paraphrase — held to a much tighter bar than the general-purpose
# CLAIM_MATCH_THRESHOLD above.
SUPPORTED_BY_MATCH_THRESHOLD = 0.85
# claim["text"] is allowed to be a loose paraphrase of its supported_by
# quote (the common, legitimate case) — this only needs to catch claims
# whose text is about a different subject than what supported_by cites.
CLAIM_TEXT_OVERLAP_THRESHOLD = 0.35
PRIMARY_SOURCE_FRANCHISES = {"vendor_watch", "policy_corner"}
_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*%?")
_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "was", "are", "were", "by", "at", "this", "that", "from", "as",
    "its", "it", "be", "has", "have", "had", "new", "now", "will", "not",
    "no", "report", "request", "available",
}
_WORD_RE = re.compile(r"[a-z0-9]+")


def _is_safe_host(hostname: str) -> bool:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for _f, _t, _p, _c, sockaddr in infos:
        try:
            addr = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return False
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return False
    return True


def _is_bot_challenge(resp: requests.Response) -> bool:
    """True if a 4xx looks like a bot-protection challenge, not a dead link.

    Found live, on this pipeline's own first real draft: producthunt.com
    403s *every* automated request — default headers, a full realistic
    browser header set, didn't matter — serving a Cloudflare "Just a
    moment..." JS challenge page (`cf-mitigated: challenge`). No HTTP-only
    client can pass that, ever, so treating it as a confirmed-dead link
    would permanently hard-block every Product Hunt-sourced item, forever.
    """
    if resp.headers.get("cf-mitigated") == "challenge":
        return True
    return "cloudflare" in resp.headers.get("server", "").lower() and resp.status_code == 403


def check_link(url: str, session: requests.Session | None = None) -> tuple[str, str]:
    """Returns (status, detail). status is "ok", "dead", or "unverifiable".

    "unverifiable" means a bot-protection challenge blocked the check
    itself, not that the URL was confirmed to not exist — treated as a
    flag for the human checklist to click through by hand, not a block.
    """
    if not url:
        return "dead", "missing URL"
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return "dead", f"unsupported scheme: {parts.scheme!r}"
    if not parts.hostname or not _is_safe_host(parts.hostname):
        return "dead", "URL resolves to a private/unsafe host"

    getter = session.head if session is not None else requests.head
    getter_fallback = session.get if session is not None else requests.get
    try:
        resp = getter(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code >= 400 or resp.status_code == 405:
            resp = getter_fallback(url, timeout=REQUEST_TIMEOUT, allow_redirects=True, stream=True)
    except requests.RequestException as exc:
        return "dead", f"request failed: {exc}"

    if resp.status_code >= 400:
        if _is_bot_challenge(resp):
            return "unverifiable", f"HTTP {resp.status_code} (bot-protection challenge, not confirmed dead)"
        return "dead", f"HTTP {resp.status_code}"
    return "ok", f"HTTP {resp.status_code}"


def _fuzzy_contains(claim_text: str, excerpt: str, threshold: float = CLAIM_MATCH_THRESHOLD) -> bool:
    """True if some window of excerpt plausibly supports claim_text.

    Found live, on the pipeline's own first real draft: a claim whose
    supported_by was a *verbatim* substring of the excerpt still got
    flagged. Root cause was the old fixed `claim_length + 20` window —
    SequenceMatcher.ratio() = 2*M/(len(a)+len(b)), so padding a perfect
    match with 20 irrelevant characters mathematically caps the achievable
    ratio (~0.836 for a 51-char claim) *below* the 0.85 threshold, no
    matter how exact the match is. Shorter, more precisely quoted claims
    were paradoxically the ones most likely to get wrongly flagged. An
    exact-substring check now short-circuits before any fuzzy scoring is
    needed, and the sliding window is sized to the claim itself (no fixed
    padding) for the genuine near-match case.
    """
    if not claim_text or not excerpt:
        return False
    claim_lower = claim_text.lower()
    excerpt_lower = excerpt.lower()

    if claim_lower in excerpt_lower:
        return True

    whole_ratio = difflib.SequenceMatcher(None, claim_lower, excerpt_lower).ratio()
    if whole_ratio >= threshold:
        return True

    window = max(len(claim_lower), 40)
    step = max(window // 4, 1)
    best = 0.0
    for start in range(0, max(1, len(excerpt_lower) - window + 1), step):
        chunk = excerpt_lower[start:start + window]
        best = max(best, difflib.SequenceMatcher(None, claim_lower, chunk).ratio())
        if best >= threshold:
            return True
    return False


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER_RE.findall(text)}


def _numbers_grounded(supported_by: str, excerpt: str) -> bool:
    """False if supported_by cites a number that isn't present verbatim in the excerpt.

    Catches a single-digit/fact swap (e.g. "20%" -> "80%") in an otherwise
    near-verbatim quote, which whole-string character similarity is mostly
    blind to.
    """
    claim_numbers = _numbers(supported_by)
    if not claim_numbers:
        return True
    return claim_numbers <= _numbers(excerpt)


def _term_overlap(claim_text: str, supported_by: str) -> float:
    """Fraction of claim_text's meaningful terms also present in supported_by."""
    claim_terms = {t for t in _WORD_RE.findall(claim_text.lower()) if t not in _STOPWORDS and len(t) > 1}
    if not claim_terms:
        return 0.0
    quote_terms = {t for t in _WORD_RE.findall(supported_by.lower()) if t not in _STOPWORDS and len(t) > 1}
    return len(claim_terms & quote_terms) / len(claim_terms)


def verify_entry(entry: dict, ranked_by_cluster: dict, session: requests.Session | None = None) -> dict:
    reasons: list[str] = []
    status = "clear"

    cid = entry.get("cluster_id")
    cluster = ranked_by_cluster.get(cid)
    if cluster is None:
        status = "blocked"
        reasons.append(f"cluster_id {cid!r} not found in this week's data/ranked")
    elif entry.get("url") != cluster.get("url"):
        status = "blocked"
        reasons.append(
            f"entry url {entry.get('url')!r} does not match cited cluster_id {cid!r}'s url {cluster.get('url')!r}"
        )

    url_status, detail = check_link(entry.get("url", ""), session=session)
    if url_status == "dead":
        status = "blocked"
        reasons.append(f"url failed: {detail}")
    elif url_status == "unverifiable":
        if status == "clear":
            status = "flagged"
        reasons.append(f"url unverifiable: {detail} — confirm by hand")

    franchise = entry.get("franchise", "weekly")
    primary = entry.get("primary_source_url", "")
    if franchise in PRIMARY_SOURCE_FRANCHISES and not primary:
        status = "blocked"
        reasons.append(f"franchise {franchise!r} requires primary_source_url")
    elif primary:
        primary_status, detail = check_link(primary, session=session)
        if primary_status == "dead":
            status = "blocked"
            reasons.append(f"primary_source_url failed: {detail}")
        elif primary_status == "unverifiable":
            if status == "clear":
                status = "flagged"
            reasons.append(f"primary_source_url unverifiable: {detail} — confirm by hand")

    excerpt = (cluster or {}).get("cluster_excerpt", "")
    unsupported = []
    for claim in entry.get("claims", []):
        supported_by = claim.get("supported_by", "")
        text = claim.get("text", "")
        quote_grounded = _fuzzy_contains(
            supported_by, excerpt, threshold=SUPPORTED_BY_MATCH_THRESHOLD
        ) and _numbers_grounded(supported_by, excerpt)
        text_grounded = _term_overlap(text, supported_by) >= CLAIM_TEXT_OVERLAP_THRESHOLD
        if not (quote_grounded and text_grounded):
            unsupported.append(text or "(no claim text)")

    if unsupported:
        if status == "clear":
            status = "flagged"
        reasons.append(f"unsupported claims (re-check against excerpt): {unsupported}")

    if entry.get("approved") and status == "blocked":
        status = "flagged"
        reasons.append(f"human-approved override: {entry.get('approved_reason', 'no reason recorded')}")

    return {
        "cluster_id": entry.get("cluster_id"),
        "title": entry.get("title"),
        "status": status,
        "reasons": reasons,
    }


def verify_draft(iso_week: str, session: requests.Session | None = None) -> list[dict]:
    draft_path = os.path.join("digest", "draft", f"{iso_week}.json")
    ranked_path = os.path.join("data", "ranked", f"{iso_week}.json")

    draft = read_json(draft_path)
    ranked_by_cluster = {c["cluster_id"]: c for c in read_json(ranked_path)}

    return [verify_entry(entry, ranked_by_cluster, session=session) for entry in draft]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iso-week", default=None)
    parser.add_argument("--assert-clear", action="store_true")
    args = parser.parse_args()

    iso_week = args.iso_week or iso_week_str()
    with requests.Session() as session:
        results = verify_draft(iso_week, session=session)

    out_path = os.path.join("digest", "verification", f"{iso_week}.json")
    write_json(out_path, results)

    blocked = [r for r in results if r["status"] == "blocked"]
    flagged = [r for r in results if r["status"] == "flagged"]
    clear = len(results) - len(blocked) - len(flagged)
    print(f"[verify] {len(results)} entries: {clear} clear, {len(flagged)} flagged, {len(blocked)} blocked")
    for r in results:
        if r["status"] != "clear":
            print(f"  {r['status'].upper()} {r['cluster_id']} ({r['title']}): {r['reasons']}")

    if args.assert_clear:
        all_clear = "true" if not blocked else "false"
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write(f"all_clear={all_clear}\n")
        if blocked:
            sys.exit(1)


if __name__ == "__main__":
    main()
