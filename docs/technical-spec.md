# Research Pipeline — Technical Build Spec

> Rev. 2 — extended to match `guardrail-radar-project-plan.md`'s automation map and content-integrity rules. Changes from Rev. 1: excerpt capture (§6), a review-packet/draft handoff (§12), and an automated verification stage (§13) that gates the generative "why this matters" commentary before it's ever sent. Everything else is unchanged.

## 1. Purpose

Automated, zero-cost content-discovery pipeline for a fintech AI-assisted-software-development newsletter. Discovers content showing **real human engagement** (not just keyword matches) at the intersection of: AI-assisted software development + regulated/enterprise engineering constraints (compliance, data governance, vendor risk, audit trails), with fintech as the primary vertical anchor.

Output is two things, not one:
1. A ranked weekly **review packet** — candidates plus stored source excerpts, ready for a human (with Claude assisting) to draft source-grounded commentary against.
2. A verified, ready-to-send **digest** — the review packet's items, plus the human/Claude-drafted commentary, only after that commentary has passed the automated verification checks in §13.

This pipeline surfaces and verifies candidates and drafts; it does not auto-publish, and it does not generate commentary unsupervised.

## 2. Constraints

- **Zero dollar budget.** No cloud provider account (no AWS/GCP/Azure), no paid APIs, no paid SaaS tiers. This includes no paid LLM API calls from CI — any generative drafting happens in the maintainer's own interactive Claude session, not a scripted API call, so it costs nothing beyond time.
- **No cloud account risk.** Everything must run on GitHub's free infrastructure only.
- **Solo maintainer.** Prefer simple, debuggable, file-based state over infra complexity.
- **No unsupervised generative content.** Anything written *about* a source (as opposed to extracted verbatim from it) must pass through the verification stage (§13) and a bounded human checklist before it can ship. This is a permanent design constraint, not a launch-phase scaffold to remove later.

## 3. High-level architecture

```
GitHub Actions (cron schedule, daily)
  ├─ matrix job: connector: hn | reddit | github | lobsters | producthunt
  │     each connector script → writes data/raw/<source>/<date>.json
  │     (each item now includes a captured source excerpt — see §6)
  ├─ job: normalize + dedup + score (runs after matrix jobs complete)
  │     reads all data/raw/*/<date>.json → writes data/ranked/<iso-week>.json
  └─ job: render review packet
        reads data/ranked/<iso-week>.json → writes digest/review/<iso-week>.md
        (extractive summaries only — no generation, nothing to verify here)
        opens a "review packet ready" GitHub Issue as the internal notification
        (no external service, no new secret — never a subscriber-facing send,
        see §15.2)

[human + Claude, outside CI]
  reads digest/review/<iso-week>.md → writes digest/draft/<iso-week>.json
  (source-grounded generative notes, one Claude-assisted session, see project plan §06)

GitHub Actions (workflow_dispatch, run once the draft above is committed)
  ├─ job: verify
  │     reads digest/draft/<iso-week>.json + data/ranked/<iso-week>.json
  │     checks link resolution + citation cross-check + claims-ledger diff
  │     writes digest/verification/<iso-week>.json (pass/flag per entry)
  ├─ [human checklist against the flags — see project plan §06]
  └─ job: render final digest
        reads the approved draft → writes digest/<iso-week>.md and site/index.html
        deploys site/ to GitHub Pages

[human, outside CI]
  pastes digest/<iso-week>.md into Beehiiv and sends
  (no free-tier publish API — this is the one irreducible manual step;
  see §15.3 and the project plan's resolved platform decision)
```

All state lives in the git repo (JSON/markdown files). GitHub Actions provides the compute and the scheduler. GitHub Pages provides free static hosting for the public digest.

## 4. Repository structure

```
research-pipeline/
├── .github/
│   └── workflows/
│       ├── daily-ingest.yml            # runs connectors daily
│       ├── weekly-review-packet.yml    # score/rank/render packet, notify maintainer
│       └── weekly-verify-and-publish.yml  # workflow_dispatch: verify draft, render + deploy
├── connectors/
│   ├── hn.py
│   ├── reddit.py
│   ├── github.py
│   ├── lobsters.py
│   └── producthunt.py
├── pipeline/
│   ├── schema.py                  # shared normalized item schema (dataclass/pydantic)
│   ├── excerpt.py                 # source-text capture + per-source fallbacks (§6)
│   ├── dedup.py                   # URL + title-similarity clustering
│   ├── score.py                   # velocity-weighted scoring
│   ├── filter.py                  # keyword/tag relevance filtering
│   ├── verify.py                  # link resolution, citation cross-check, claims-ledger diff (§13)
│   ├── render.py                  # review-packet + final digest + HTML rendering
│   └── notify.py                  # opens a "review packet ready" GitHub Issue (§15.2)
├── data/
│   ├── raw/<source>/<YYYY-MM-DD>.json
│   ├── interim/<YYYY-Www>.json      # dedup'd + scored working file, overwritten by each stage (§9-§11)
│   └── ranked/<YYYY-Www>.json
├── digest/
│   ├── review/<YYYY-Www>.md        # extractive-only packet, drafting input
│   ├── draft/<YYYY-Www>.json       # human/Claude-authored generative notes, verification input
│   ├── verification/<YYYY-Www>.json # verify.py output: pass/flag per draft entry
│   └── <YYYY-Www>.md               # final, verified, ready-to-paste digest
├── site/
│   └── index.html                 # published via GitHub Pages
├── config/
│   ├── keywords.yml                # relevance keyword/tag rules
│   └── sources.yml                 # per-source config (subreddits, search terms)
├── requirements.txt
├── README.md
└── tests/
    ├── test_dedup.py
    ├── test_score.py
    ├── test_filter.py
    ├── test_excerpt.py
    └── test_verify.py
```

## 5. Normalized data schema

Every connector must output a list of items in this shape (JSON):

```json
{
  "id": "sha256 hash of normalized_url",
  "source": "hn | reddit | github | lobsters | producthunt",
  "title": "string",
  "url": "string (canonicalized: strip tracking params, lowercase host)",
  "raw_score": 0,
  "comment_count": 0,
  "posted_at": "ISO8601 UTC timestamp",
  "fetched_at": "ISO8601 UTC timestamp",
  "excerpt": "string — captured source text, see §6",
  "excerpt_status": "ok | partial | none",
  "source_meta": {
    "_comment": "source-specific extras, e.g. subreddit name, repo total_stars"
  }
}
```

`id` = `sha256(normalized_url)` — this is the dedup key across sources.

`excerpt` / `excerpt_status` are new in Rev. 2: they exist specifically so a later drafting step never has to write commentary from a bare title, which is the single biggest hallucination risk in the whole pipeline (see project plan §06).

## 6. Excerpt capture (`pipeline/excerpt.py`)

Every connector calls a shared helper after normalizing an item, before writing it to `data/raw/<source>/<date>.json`.

1. **Primary attempt** — fetch the item's `url` (timeout 5s, one retry), extract `<meta name="description">` or `og:description`, falling back to the first substantial `<p>` tag. Use `beautifulsoup4` (the one new dependency this revision adds — plain regex parsing across arbitrary third-party HTML is too fragile to trust for something that later gets treated as ground truth).
2. **Per-source fallback**, used when the primary attempt fails (paywall, JS-rendered page, blocked fetch, non-200 status) or when the item has no useful external page at all:
   - **HN**: `story_text` (Ask HN/Show HN body) if present, else the top HN comment's text.
   - **Reddit**: `selftext` for self-posts; otherwise the post title plus the top comment's body.
   - **GitHub**: repo `description` plus the README's first paragraph (`GET /repos/{owner}/{repo}/readme`, base64-decoded).
   - **Lobsters**: the story's own `description` field if present.
   - **Product Hunt**: the post's `tagline` plus the first paragraph of its `description`.
3. **Truncate** the captured text to ~1,000 characters — enough to ground a two-to-three-sentence note, not so much that a connector run balloons in size.
4. **Record `excerpt_status`**: `ok` (primary fetch succeeded), `partial` (fallback text used), or `none` (nothing usable found — both attempts failed). An item with `excerpt_status: none` can still be discovered, ranked, and appear in the review packet's extractive layer, but the drafting step (§12) must skip or explicitly flag it rather than invent a note with nothing to ground it in.

No new secrets are required — this reuses the same per-source auth already in place for §7/§8's connectors.

## 7. Connectors — Phase 1 (build first)

### 7.1 Hacker News (`connectors/hn.py`)
- API: Algolia HN Search API — `https://hn.algolia.com/api/v1/search_by_date?query=<term>&tags=story`
- No auth required.
- Query terms come from `config/keywords.yml` (OR'd queries, run separately, results merged).
- Extract: `title`, `url` (fallback to HN item URL if no external url), `points` → `raw_score`, `num_comments` → `comment_count`, `created_at` → `posted_at`, plus excerpt capture per §6.
- Rate limit: none documented; add 1s sleep between queries to be polite.

### 7.2 Reddit (`connectors/reddit.py`)
- API: Reddit's official API via a free "script" app (register at reddit.com/prefs/apps).
- Auth: OAuth2 client-credentials flow using `client_id` / `client_secret` stored as GitHub Actions secrets (`REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`) + a descriptive `User-Agent` string (Reddit requires this or it will 429).
- Subreddits (from `config/sources.yml`): `fintech`, `programming`, `MachineLearning`, `artificial`, `ExperiencedDevs`, `devops`, `sre`.
- Pull `new` and `top?t=week` listings per subreddit, filter by keyword match in title/selftext.
- Extract: `title`, `url`, `ups` → `raw_score`, `num_comments` → `comment_count`, `created_utc` → `posted_at`, plus excerpt capture per §6.
- Respect Reddit's rate limit (60 req/min per OAuth client) — add throttling.

### 7.3 GitHub (`connectors/github.py`)
- API: GitHub REST API (`/search/repositories`), auth via a free personal access token (`GITHUB_TOKEN` — GitHub Actions provides this automatically for API calls against the repo, but a separate PAT with broader scope should be stored as `GH_SEARCH_TOKEN` secret for search API rate limits — 5000 req/hr authenticated vs 10/min unauthenticated). No scopes are required on that PAT — it's used purely to raise the rate limit for public read-only endpoints.
- Query: repos matching keyword topics (`ai-coding`, `llm-tools`, `terraform`, `compliance`, `fintech`) created or pushed in the last 30 days.
- **Signal: log-scaled total stargazers_count, not true velocity.** The original design called for `stars_last_7d` via the stargazers endpoint's `starred_at` timestamps (`Accept: application/vnd.github.star+json`) — confirmed against the real API (not assumed) that this endpoint now 404s for any repo the token holder doesn't own or collaborate on, regardless of token scope: tested against `torvalds/linux` and `octocat/Hello-World` with a fully-scoped token (both 404), versus a repo the token's own account owns (succeeds). GitHub has restricted third-party stargazer-timestamp enumeration outright, so true velocity is no longer obtainable through this API for the repos this connector actually searches. `raw_score` is instead `int(math.log1p(stargazers_count) * 100)` — the search endpoint already returns total star count for free, and the log scale keeps a repo with hundreds of thousands of stars from swamping the shared cross-source velocity formula in §10 on the strength of nothing but a routine push. Monotonic, but a popularity proxy, not a momentum one.
- Extract: `full_name` → `title`, `html_url` → `url`, log-scaled `stargazers_count` → `raw_score` (raw count also kept in `source_meta.total_stars`), `open_issues_count` as a secondary signal in `source_meta`, plus excerpt capture per §6 (repo description + README first paragraph).

## 8. Connectors — Phase 2

### 8.1 lobste.rs (`connectors/lobsters.py`)
- Public JSON feed: `https://lobste.rs/newest.json` (and `/hottest.json`), no auth.
- Filter by tags (`ai`, `security`, `finance` if present) and keyword match.
- Extract: `title`, `url`, `score` → `raw_score`, `comment_count`, `created_at` → `posted_at`, plus excerpt capture per §6.

### 8.2 Product Hunt (`connectors/producthunt.py`)
- Free GraphQL API, requires a free developer token (`PRODUCTHUNT_TOKEN` secret).
- Query posts tagged with AI/developer-tools topics from the last 7 days.
- Extract: `name` → `title`, `url`, `votesCount` → `raw_score`, `commentsCount` → `comment_count`, `createdAt` → `posted_at`, plus excerpt capture per §6.

## 9. Deduplication (`pipeline/dedup.py`)

`pipeline.dedup`, `pipeline.score`, and `pipeline.filter` hand off through a
single shared working file, `data/interim/<iso-week>.json`: dedup writes it,
score reads and overwrites it with `velocity_score`/`item_score`/
`cluster_score` added, and filter reads it to produce the final
`data/ranked/<iso-week>.json`. This is an implementation addition beyond the
original repo-structure sketch (§4) — kept as an inspectable file between
stages rather than an in-memory hand-off, matching the "simple, file-based
state" preference in §2. See CHANGELOG.md.

1. Group items by exact `id` (normalized URL hash) — direct duplicates merge, summing `raw_score`/`comment_count` isn't correct across sources, so instead: keep each source's raw item but tag them with a shared `cluster_id`.
2. For near-duplicates (same story, different URL — e.g. a blog post vs. its HN discussion vs. a Reddit crosspost), use title similarity: normalize titles (lowercase, strip punctuation) and cluster via `difflib.SequenceMatcher` ratio > 0.85, or token-set overlap (Jaccard) > 0.7 — no ML dependency needed.
3. A `cluster_id` groups all items about the same underlying story. Clusters spanning 2+ distinct sources get a **cross-source bonus** in scoring (below) — this is itself a strong quality signal.
4. When merging items into a cluster, keep the excerpt with the best `excerpt_status` (`ok` > `partial` > `none`) as the cluster's representative excerpt — this is what the drafting step in §12 will be shown.

## 10. Scoring (`pipeline/score.py`)

Per-item velocity score:

```
hours_since_post = max(1, (now - posted_at).total_hours)
velocity_score = raw_score / hours_since_post
discussion_ratio = comment_count / max(1, raw_score)   # rewards genuine discussion, not just upvotes
item_score = velocity_score * (1 + min(discussion_ratio, 1.0))
```

Per-cluster score (used for final ranking):

```
cluster_score = max(item_score for items in cluster) * (1 + 0.25 * (distinct_sources_in_cluster - 1))
```

Rank clusters by `cluster_score` descending. Output top 30 per week to `data/ranked/<iso-week>.json`.

Scoring weights (the constants above) are tuned by hand, quarterly, against real reply/click data — not auto-adjusted by the pipeline. See project plan §05: auto-tuning a filter against a solo newsletter's early, low-volume engagement data risks overfitting it to noise rather than signal.

## 11. Relevance filtering (`pipeline/filter.py`)

- `config/keywords.yml` defines two term sets: `core_terms` (AI-assisted dev: "copilot", "claude code", "cursor", "llm coding", "ai pair programming", "code generation") and `context_terms` (regulated/enterprise: "compliance", "fintech", "banking", "audit", "data governance", "vendor risk", "sox", "air-gapped", "on-prem llm").
- An item passes the filter if it matches **at least one term from each set** OR matches 1+ terms from `core_terms` with high engagement (top-quartile velocity_score) — this lets a well-engaged pure-AI-dev story through even without an explicit fintech mention, since compliance-minded readers still want to know about it. Loosened from an original top-decile/2+-terms bypass after real data showed the AND-requirement passed zero HN or GitHub items in a 345-item single-day pull — regulated-industry relevance is rarely spelled out explicitly in a terse title even when the story is a good editorial fit, and the human curator in `draft-digest` still decides what actually ships, so a broader ranked pool here only affects curation material, not what readers see.
- Keep this rules-based for now (explicitly not an ML/embedding step) — no paid API dependency, fully deterministic, easy to tune by editing YAML.

## 12. Review packet & drafting handoff

This is the seam between the automated pipeline and the human/Claude-assisted drafting session described in the project plan (§05, §06).

### 12.1 Review packet (`digest/review/<iso-week>.md`)

Generated by `pipeline/render.py` directly from `data/ranked/<iso-week>.json` — extractive only, no generation, nothing here needs verification. For each of the top ~10 clusters: title (linked), source(s), score, and the cluster's representative `excerpt` (verbatim, truncated as stored). Clusters where every item has `excerpt_status: none` are marked `[insufficient source text]` so the drafting step knows to skip or handle them with extra care rather than draft from nothing.

### 12.2 Draft (`digest/draft/<iso-week>.json`)

Authored by the maintainer, Claude-assisted, working from the review packet. A JSON object with three top-level keys: `subject` (a string), `intro` (a string), and `items` (one entry per item the issue will include):

```json
{
  "subject": "the literal Beehiiv subject line — required, distinct from intro",
  "intro": "a short connective narrative for the whole issue — dry wit, still professional; optional, empty string is valid",
  "items": [
    {
      "cluster_id": "must match an id present in data/ranked/<iso-week>.json",
      "title": "string",
      "url": "string",
      "franchise": "weekly | vendor_watch | policy_corner | reader_qa",
      "category": "breaking | new_product | notable | field_notes — the table-of-contents grouping, required on every item",
      "hook": "one plain-English sentence, front-running the item, on why it's worth a look — required on every item",
      "note": "the generative \"why this matters\" text — written only from the cluster's stored excerpt",
      "claims": [
        {"text": "a specific claim made in note", "supported_by": "the excerpt phrase that supports it"}
      ],
      "primary_source_url": "required and must resolve when franchise is vendor_watch or policy_corner; omit otherwise"
    }
  ]
}
```

The `claims` array is the claims ledger referenced in the project plan §06 — it's what makes the human checklist a scan of flags rather than a re-derivation from scratch, and it's what `verify.py` (§13) actually checks against.

`subject` was added after a design-critique pass found no field anywhere in the pipeline produced an email subject line, leaving it improvised at send time. Required, distinct from `intro` — it's the one sentence that has to work before anything else gets read, so it gets its own drafting attention rather than reusing `intro`'s opening clause. Not rendered on `site/index.html` (email-only concept); `pipeline/render.py` surfaces it as a clearly-labeled line at the top of `digest/<iso-week>.md`, above the issue's own heading, for the human doing the manual paste-and-send step (§15.3) to copy into Beehiiv's subject field.

`intro` was added after real user feedback on the first live issue: three isolated per-item notes with no frame or synthesis read as a bare link list, not a newsletter. It's connective tissue for the whole issue — a shared theme across the included items, or an honest "thin week" note — not a factual claim about any one source, so `verify.py` doesn't check it against an excerpt or a claims ledger; it still must not invent specifics that aren't grounded in the items it introduces. `pipeline/render.py` renders it once, at the top of the issue, in both `digest/<iso-week>.md` and `site/index.html`.

`hook` was added after real user feedback on the next issue: readers need a one-sentence, plain-English reason an item is worth their time — what's genuinely interesting or useful about it — before the longer, more skeptical `note`. Unlike `intro` it's required on every item, not optional, and it's usually a tight paraphrase of the excerpt's own stated pitch rather than something invented. Like `intro`, it doesn't get its own claims-ledger entries and isn't checked against an excerpt by `verify.py`, but it must still be grounded only in the excerpt — no invented superlatives, stats, or specifics. A later design-critique pass found `hook` rendering as a subordinate line under the item's raw, often jargon-dense source `title` — readers' best-written copy demoted under scraped metadata. `pipeline/render.py` now renders `hook` *as the item's headline* (linked to `url`), with the cleaned `title` — source-platform prefixes like `Show HN:` stripped for display, see §14 — demoted to a small secondary caption underneath. An item with no `hook` falls back to `title` as its own headline.

`category` was added after a direct user request for a table of contents grouped by area/criticality rather than a flat list. It's a required, fixed four-value enum — `breaking` (urgent: incidents, compromises, outages, a vendor silently changing behavior), `new_product` (a launch), `notable` (impressive/surprising, not urgent — used sparingly), or `field_notes` (practitioner commentary/culture, not a product or news event) — distinct from `franchise`, which is about the newsletter's recurring column format and doesn't have to line up with it. `pipeline/render.py` builds one table-of-contents block per issue from it, in a fixed display order, omitting any category with no items that week; each item gets a stable `id="item-<cluster_id>"` anchor in `site/index.html` for the TOC to link to. `verify.py` doesn't check `category` — it's a classification, not a factual claim.

## 13. Verification (`pipeline/verify.py`)

Runs in CI (`weekly-verify-and-publish.yml`, workflow_dispatch) once a `digest/draft/<iso-week>.json` has been committed. No paid API involved — every check below is either an HTTP request or a string-matching pass.

1. **Link resolution** — `GET` (or `HEAD`, falling back to `GET` on 405) every `url` and `primary_source_url` in the draft. A confirmed non-2xx status or a timeout marks that entry `blocked`. A 4xx that carries a Cloudflare bot-challenge signature (`cf-mitigated: challenge`, or a `cloudflare` server header on a 403) is treated as `unverifiable`, not `blocked` — found live on the pipeline's own first real draft: producthunt.com 403s every automated request, realistic browser headers included, serving a JS challenge no HTTP-only client can ever pass. Hard-blocking on that would have permanently blocked every Product Hunt-sourced item. HTTP 429 gets the same `unverifiable` treatment regardless of headers — found live drafting a later issue: this pipeline's own request volume against news.ycombinator.com in one session rate-limited two real, browser-confirmed links, and 429 by definition never means "confirmed doesn't exist." `unverifiable` still downgrades the entry to `flagged` rather than passing it silently — a real browser click-through in the human checklist (§06) is what actually resolves it.
2. **Citation cross-check** — every `cluster_id` in the draft must exist in that week's `data/ranked/<iso-week>.json`, and the entry's own `url` must match that cluster's stored `url` exactly. Either mismatch marks the entry `blocked` — this is what catches a misremembered/invented story, or a citation whose headline was edited to point at a different one, before it ships.
3. **Claims-ledger diff** — for each `{text, supported_by}` pair in `claims`, checks that `supported_by` is grounded in the cluster's stored `excerpt` (exact substring first, then a fuzzy fallback for near-verbatim quotes — `difflib.SequenceMatcher`, same technique already used in dedup, no new dependency) and that `claim.text` itself has real term-overlap with its own `supported_by` quote, not just a citation that happens to be real. A short, precisely-quoted `supported_by` is checked as an exact substring specifically so a tight window-padding calculation can't mathematically cap a perfect match below threshold — found live on the pipeline's own first real draft, where several verbatim quotes were wrongly flagged for exactly that reason. A claim that fails either check marks that specific claim `flagged`, not the whole entry blocked — it's a signal for the human checklist, not an auto-reject.
4. **Primary-source requirement** — any entry with `franchise: vendor_watch` or `franchise: policy_corner` and a missing or unresolvable `primary_source_url` is marked `blocked`, regardless of how the rest of its checks pass. Vendor and policy claims don't ship on a secondary or inferred citation.

Output: `digest/verification/<iso-week>.json`, one record per draft entry with a status (`clear`, `flagged`, `blocked`) and the specific reason(s). This file is what the bounded human checklist (project plan §06) is read against — the check is "scan the flags and blocks, click every link once, confirm tone, approve," not an open-ended fact hunt.

`verify.py` never edits or removes anything from the draft itself — it only annotates. A human decides what to do with a `flagged`/`blocked` entry (fix the note, drop the item, or override with a documented reason); the pipeline doesn't auto-correct claims about a subject as consequential as compliance or vendor risk.

## 14. Digest rendering (`pipeline/render.py`)

Two distinct render targets, reflecting the two-layer content model in the project plan (§06):

- **Review packet** (§12.1): extractive-only, generated straight from `data/ranked/<iso-week>.json`, no dependency on drafting or verification.
- **Final digest**, generated only after a draft's entries are all `clear` or explicitly human-approved past a `flagged`/`blocked` state:
  - Output 1: `digest/<iso-week>.md` — ranked list, each entry: title (linked), source(s), score, the extractive excerpt, and the verified generative note.
  - Output 2: `site/issues/<iso-week>.html` — a standalone, fully self-contained page for that one issue (full TOC + items, its own `<title>`/canonical url/Open Graph & Twitter Card meta tags using `subject` as the social description). Added after a direct user request for past issues linkable on social media — before this, the only referenceable url was the homepage, which has no per-issue title/description, so a shared link always produced the same generic preview regardless of which issue was meant. A plain file overwrite per render, not idempotent-marker-based (see Output 3) — no shared document to corrupt.
  - Output 3: `site/index.html` — the homepage archive, one short **teaser** per issue (`_render_homepage_teaser_html`: heading linking to that issue's page, a description derived from `subject`/`intro`, the "N items across N sources — ..." summary line, and a "Read the full issue →" link) — not the full content inline, which used to make the homepage grow without bound as issues accumulated and gave every issue the same non-shareable url. Each week's teaser block is wrapped in a matched pair of `<!-- week:<iso-week> -->` / `<!-- /week:<iso-week> -->` HTML comments so a re-render can find and replace its own prior block unambiguously — found necessary after the site initially shipped with only a bare linked title per item (the excerpt and note went into `digest/<iso-week>.md` but never reached the public page), and the first fix for that used a structural-tag terminator that broke again the moment items carried real nested markup. The marker mechanism is unchanged by the teaser-card rework; only the content it wraps got smaller.
  - `SITE_BASE_URL` (`pipeline/render.py`) — the real, confirmed GitHub Pages url (`https://roberjo.github.io/guardrail-radar`, checked via `gh api repos/roberjo/guardrail-radar/pages`, not guessed) — used to build the absolute `canonical`/`og:url` values every issue page needs for a correct social-platform preview.

**Format-audit additions** (comparison against TLDR, tl;dr sec, and The Batch — see the published format-audit artifact): none require a new drafted field, so `verify.py` and the draft schema are unaffected.

- **Read-time estimate** — `_read_time_minutes(hook, excerpt, note)` computes `max(1, round(word_count / 200))` per item and renders it as a badge (`site/index.html`) or a `N min read` suffix (`digest/<iso-week>.md`), next to the category badge.
- **Category badge per item, with an icon** — `category` (§12.2) was previously only surfaced in the table of contents; it now also renders on every item itself (on its issue page), so it registers before a reader parses the headline. A design-critique pass found the page had zero visual texture, so each badge also carries a small inline-SVG glyph (`CATEGORY_ICON_SVG`) in the item's own hue via `currentColor`.
- **Collapsible excerpt, after the note** — on the issue page only, the verbatim excerpt is wrapped in `<details><summary>Read the source excerpt</summary>…</details>`. Originally rendered between the hook and the note; a design-critique pass found that placement broke the hook-to-note reading flow for what's supporting evidence, not the main copy, so it now renders after the note in both `digest/<iso-week>.md` (as a blockquote) and the issue page — `<details>` can't be relied on to survive a paste into Beehiiv, so the markdown version stays always-visible.
- **Redundant stats line cut from the issue page, revived on the homepage teaser** — the "N items across N sources — ..." line (`_teaser_summary_line`, formerly `_issue_stats_line`) was cut from the per-issue view after a design-critique pass found it repeated, almost verbatim, information the table of contents already conveys better, with working links, one scroll below it. It's back, unchanged in substance, as the homepage teaser's at-a-glance summary — a genuinely different role once the teaser has no TOC of its own to duplicate.
- **Hottest-to-coldest ordering, gradient, and hue bands** — `CATEGORY_ORDER` is `notable, breaking, field_notes, new_product`, not urgency-first — this is the *reading order*. Direct user request: lead with the most interesting item, not the most urgent one — the opposite of the inverted-pyramid convention TLDR/tl;dr sec/The Batch all use, closer to how engagement-first newsletters like Morning Brew choose a lead story for interest value over urgency. Every colored element (category badge, its icon, the item's headline and left-border, and the matching TOC group/link) reads its color from a single per-item `--hot-hue` CSS custom property (`hsl(var(--hot-hue) var(--hot-s) var(--hot-l))`). `_hotness_order` (`pipeline/render.py`) computes it: category sets the coarse band (`HOTTEST_HUE`..`COOLEST_HUE`, red through orange and yellow to green), and each item's real `cluster_score` places it within that band, hottest-scoring first. A design-critique pass found this coupling `CATEGORY_ORDER`'s *reading-order* rank to the *hue-band* rank had a real side effect: `notable` (a curiosity item) owned the alarm-red end of the gradient while `breaking` (an actual incident) rendered in a calmer amber, for an audience where red specifically reads as "incident." `HUE_BAND_ORDER` (`breaking, notable, field_notes, new_product`) now controls hue-band assignment separately from `CATEGORY_ORDER`'s reading order — `breaking` owns the red end regardless of where it falls in reading order. `render_final_digest` calls `_hotness_order` once, right after loading `draft`, so the body reads in the same order (and gradient) the TOC promises.
- **Headline hierarchy: hook, not raw title** — see `hook`'s entry in §12.2 above.
- **Title cleanup for display** — `_clean_display_title` strips a leading `Show HN:`/`Ask HN:`/`Tell HN:` (HN's own submission-type metadata, not part of the title) before rendering anywhere — the TOC, the item headline's secondary caption, the markdown heading. The underlying `entry["title"]` used for citation matching is untouched.
- **Masthead brand mark, favicon, byline, subscribe CTA** — `site/index.html`'s masthead (and, in its compact form, each issue page's own header) carries an inline-SVG brand mark (`BRAND_MARK_SVG` — a radar sweep held inside four monitoring brackets; the mark and rationale live in the project's design exploration, not in this pipeline) alongside the `<h1>`, plus `site/favicon.svg` as the browser-tab icon and a one-line byline (homepage only). A design-critique pass found the site had zero credibility signal (no author) and zero conversion path (no subscribe link anywhere, verified by grepping the shipped HTML). The subscribe CTA markup and styling (`.subscribe-btn`) are in place — on the homepage and on every issue page — but commented out: no Beehiiv publication exists yet (project plan §11), and shipping a link to a guessed or placeholder URL on a live public page is worse than no link at all.
- **`site/og-image.png`** — a static 1200×630 branded social-share image (brand mark + wordmark + tagline, rendered once via a real browser screenshot, not generated per-issue) referenced by every issue page's `og:image`/`twitter:image`. A per-issue custom image (e.g. rendering that week's hottest headline onto the card) is a real future enhancement, not built here — out of scope for what a direct request for "linkable past issues" needed.
- **`site/status.html`** — a read-only, unauthenticated pipeline-status dashboard: recent runs of all three GitHub Actions workflows, the latest `daily-ingest.yml` run's per-connector job health, and the latest `digest/verification/<iso-week>.json`'s clear/flagged/blocked counts. Entirely client-side JavaScript calling the public, unauthenticated GitHub REST API at page-load time (`api.github.com/repos/roberjo/guardrail-radar/...`) — no backend, no auth, no new infrastructure, consistent with the project's zero-server design (project plan §7). Not generated by `pipeline/render.py`; a hand-authored static file like `site/index.html` itself. Linked from the homepage footer.

## 15. GitHub Actions workflows

### 15.1 `.github/workflows/daily-ingest.yml`
- Trigger: `schedule: cron: '0 12 * * *'` (adjust to preferred UTC time) + `workflow_dispatch` for manual runs.
- Job matrix over the 5 connectors, each a separate matrix entry running its script with `pip install -r requirements.txt`. Each connector now also performs excerpt capture (§6) inline.
- Final job (`needs: [matrix job]`) commits new `data/raw/**` files back to the repo using `stefanzweifel/git-auto-commit-action` (free, widely used Action) or a plain `git commit && git push` step with the built-in `GITHUB_TOKEN`.

### 15.2 `.github/workflows/weekly-review-packet.yml`
- Trigger: `schedule: cron: '0 13 * * 1'` (Monday) + `workflow_dispatch`.
- Steps: `pipeline/dedup.py` → `pipeline/score.py` → `pipeline/filter.py` → `pipeline/render.py` (review-packet target only).
- Commit `data/ranked/**` and `digest/review/**` back to the repo.
- Final step: `pipeline/notify.py` opens (or, idempotently, finds and reuses) a **GitHub Issue** — "Review packet ready: `<iso-week>`" with the candidate count and a link to the packet in its body. Originally SMTP to the maintainer's own address (the Rev. 1 spec's repurposed subscriber-send mechanism); replaced because a Gmail app password is real setup friction for a notification GitHub can deliver for free — the built-in `GITHUB_TOKEN` can open issues once the job grants `issues: write`, and GitHub's own notification system pings the repo owner exactly the way the SMTP step used to. Confirmed against the real API before adopting it, not assumed. Never a subscriber-facing send — that still only happens by hand on Beehiiv.
- Does **not** deploy to Pages and does **not** touch `digest/<iso-week>.md` — those only exist after verification (§15.3).

### 15.3 `.github/workflows/weekly-verify-and-publish.yml`
- Trigger: `workflow_dispatch` only — run by hand once `digest/draft/<iso-week>.json` has been committed (i.e., once the maintainer's Claude-assisted drafting session is done).
- Steps: `pipeline/verify.py` → write `digest/verification/<iso-week>.json` → if every entry is `clear` (or has been hand-approved past a flag, tracked via a simple `approved: true` field the maintainer adds to a flagged/blocked entry before re-running), run `pipeline/render.py` (final-digest target) → commit `digest/<iso-week>.md`, `site/**` → deploy `site/` to GitHub Pages (`actions/deploy-pages` — free, official Action).
- If any entry is still `blocked` and unapproved, the job fails loudly rather than partially publishing — a compliance-adjacent newsletter shouldn't ship an issue with an unresolved citation or a vendor claim it couldn't verify.
- No subscriber-notification step here either — sending to subscribers is the one manual, outside-of-CI step described in §3 and the project plan §05/§13.

## 16. Required GitHub Actions secrets

| Secret | Used by |
|---|---|
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | reddit.py — connector currently deferred, see §7.2 non-goals note / CHANGELOG |
| `GH_SEARCH_TOKEN` | github.py (search API rate limit); no scopes required, public-data read only |
| `PRODUCTHUNT_TOKEN` | producthunt.py |

`pipeline/notify.py` needs no repo secret at all — it uses `secrets.GITHUB_TOKEN`, which every workflow already gets automatically, gated by an explicit `issues: write` permission on the job (§15.2).

No secrets needed for `hn.py`, `lobsters.py`, `pipeline/excerpt.py`'s primary fetch path, or `pipeline/verify.py`.

## 17. Dependencies (`requirements.txt`)

```
requests
pyyaml
python-dateutil
beautifulsoup4
```

`beautifulsoup4` is the one addition in this revision, needed for excerpt capture (§6) to reliably pull a meta-description or first paragraph out of arbitrary third-party HTML — plain regex parsing is too fragile to trust for text that later gets treated as ground truth in the claims-ledger diff (§13).

Still no pandas/numpy/ML libraries — keep the runtime lightweight so Actions jobs run in seconds, not minutes.

Test/lint/type-check tooling (`pytest`, `ruff`, `mypy` + `types-*` stubs) lives in a separate `requirements-dev.txt` (`-r requirements.txt` plus those), not in `requirements.txt` itself — the three scheduled/production workflows (§15) only ever install `requirements.txt`; only `test.yml` installs `requirements-dev.txt`. See CHANGELOG.md.

## 18. Testing

- `tests/test_dedup.py`: verify near-duplicate titles cluster correctly; verify distinct stories don't over-merge; verify the best-`excerpt_status` item wins as a cluster's representative excerpt.
- `tests/test_score.py`: verify velocity math and cross-source bonus with fixed fake timestamps/scores.
- `tests/test_filter.py`: verify keyword rule combinations pass/fail as expected.
- `tests/test_excerpt.py`: verify the primary-fetch → per-source-fallback → `none` chain resolves correctly for each source, using fixture HTML/API responses (no live network calls in CI).
- `tests/test_verify.py`: verify link-resolution status handling (2xx/redirect/timeout), citation cross-check against a fixture `data/ranked` file, claims-ledger fuzzy-match thresholds, and the primary-source requirement for `vendor_watch`/`policy_corner` entries.
- Run via `pytest` in a CI step on every push (separate lightweight workflow, not the scheduled ones) — `.github/workflows/test.yml` also runs `ruff check` and `mypy connectors pipeline` ahead of the test suite, using the tooling in `requirements-dev.txt` (§17).

## 19. Build order (for Claude Code)

1. Repo scaffold + `schema.py` + `requirements.txt`.
2. `connectors/hn.py` + `pipeline/excerpt.py` (no auth needed for either — fastest to validate end-to-end).
3. `pipeline/dedup.py`, `pipeline/score.py`, `pipeline/filter.py` + unit tests, validated against HN-only data.
4. `connectors/reddit.py` + `connectors/github.py`, each wired to `pipeline/excerpt.py`.
5. `pipeline/render.py` (review-packet target) + `site/index.html` static template.
6. `.github/workflows/daily-ingest.yml`, validate via `workflow_dispatch` manual run.
7. `pipeline/notify.py` + `.github/workflows/weekly-review-packet.yml`, including the repurposed internal-notification email step.
8. `pipeline/verify.py` + `tests/test_verify.py`, validated by hand-authoring a `digest/draft/<iso-week>.json` against real review-packet output.
9. `pipeline/render.py` (final-digest target) + `.github/workflows/weekly-verify-and-publish.yml`, including GitHub Pages deploy.
10. Phase 2 connectors: `lobsters.py`, `producthunt.py`.
11. Tune `config/keywords.yml` weights based on the first quarter's real reply/click data (project plan §05) — not before.

## 20. Explicit non-goals (for this build)

- No ML/embedding-based relevance scoring (cost and complexity not justified at this scale).
- No database — git-committed JSON is the store.
- No auto-publishing to the newsletter platform — output is a curation and verification aid only; a human always pastes the final digest into Beehiiv and sends it.
- No unsupervised generative drafting — every "why this matters" note is written in a human/Claude-assisted session and gated by `verify.py` plus a bounded human checklist before it can ship (project plan §06). This is permanent, not a temporary safeguard to automate away later.
- No paid LLM API calls from CI — drafting happens interactively, not as a scripted call, so it never conflicts with the zero-budget constraint.
- No automated scoring-weight tuning off engagement data — reviewed by hand, quarterly, to avoid overfitting a filter to a small, noisy sample (project plan §05).
- No Twitter/X or LinkedIn connectors (no usable free API).
