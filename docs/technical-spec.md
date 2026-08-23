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
        sends an internal "review packet ready" notification to the maintainer
        (repurposed SMTP step — never a subscriber-facing send, see §15.2)

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
  pastes digest/<iso-week>.md into Substack/Beehiiv and sends
  (no free-tier publish API exists on either platform — this is the one
  irreducible manual step; see §15.3 and the project plan's open decisions)
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
│   └── notify.py                  # internal "review packet ready" email to the maintainer (§15.2)
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
- An item passes the filter if it matches **at least one term from each set** OR matches 2+ terms from `core_terms` with high engagement (top-decile velocity_score) — this lets a very hot pure-AI-dev story through even without an explicit fintech mention, since compliance-minded readers still want to know about it.
- Keep this rules-based for now (explicitly not an ML/embedding step) — no paid API dependency, fully deterministic, easy to tune by editing YAML.

## 12. Review packet & drafting handoff

This is the seam between the automated pipeline and the human/Claude-assisted drafting session described in the project plan (§05, §06).

### 12.1 Review packet (`digest/review/<iso-week>.md`)

Generated by `pipeline/render.py` directly from `data/ranked/<iso-week>.json` — extractive only, no generation, nothing here needs verification. For each of the top ~10 clusters: title (linked), source(s), score, and the cluster's representative `excerpt` (verbatim, truncated as stored). Clusters where every item has `excerpt_status: none` are marked `[insufficient source text]` so the drafting step knows to skip or handle them with extra care rather than draft from nothing.

### 12.2 Draft (`digest/draft/<iso-week>.json`)

Authored by the maintainer, Claude-assisted, working from the review packet. One entry per item the issue will include:

```json
{
  "cluster_id": "must match an id present in data/ranked/<iso-week>.json",
  "title": "string",
  "url": "string",
  "franchise": "weekly | vendor_watch | policy_corner | reader_qa",
  "note": "the generative \"why this matters\" text — written only from the cluster's stored excerpt",
  "claims": [
    {"text": "a specific claim made in note", "supported_by": "the excerpt phrase that supports it"}
  ],
  "primary_source_url": "required and must resolve when franchise is vendor_watch or policy_corner; omit otherwise"
}
```

The `claims` array is the claims ledger referenced in the project plan §06 — it's what makes the human checklist a scan of flags rather than a re-derivation from scratch, and it's what `verify.py` (§13) actually checks against.

## 13. Verification (`pipeline/verify.py`)

Runs in CI (`weekly-verify-and-publish.yml`, workflow_dispatch) once a `digest/draft/<iso-week>.json` has been committed. No paid API involved — every check below is either an HTTP request or a string-matching pass.

1. **Link resolution** — `GET` (or `HEAD`, falling back to `GET` on 405) every `url` and `primary_source_url` in the draft. A non-2xx status, a redirect to an unexpected domain, or a timeout marks that entry `blocked`.
2. **Citation cross-check** — every `cluster_id` in the draft must exist in that week's `data/ranked/<iso-week>.json`. A `cluster_id` that doesn't resolve marks the entry `blocked` — this is what catches a misremembered or invented story before it ships.
3. **Claims-ledger diff** — for each `{text, supported_by}` pair in `claims`, fuzzy-match `supported_by` against the cluster's stored `excerpt` (`difflib.SequenceMatcher` ratio, same technique already used in dedup — no new dependency). A `supported_by` phrase that doesn't reasonably match the excerpt marks that specific claim `flagged`, not the whole entry blocked — it's a signal for the human checklist, not an auto-reject.
4. **Primary-source requirement** — any entry with `franchise: vendor_watch` or `franchise: policy_corner` and a missing or unresolvable `primary_source_url` is marked `blocked`, regardless of how the rest of its checks pass. Vendor and policy claims don't ship on a secondary or inferred citation.

Output: `digest/verification/<iso-week>.json`, one record per draft entry with a status (`clear`, `flagged`, `blocked`) and the specific reason(s). This file is what the bounded human checklist (project plan §06) is read against — the check is "scan the flags and blocks, click every link once, confirm tone, approve," not an open-ended fact hunt.

`verify.py` never edits or removes anything from the draft itself — it only annotates. A human decides what to do with a `flagged`/`blocked` entry (fix the note, drop the item, or override with a documented reason); the pipeline doesn't auto-correct claims about a subject as consequential as compliance or vendor risk.

## 14. Digest rendering (`pipeline/render.py`)

Two distinct render targets, reflecting the two-layer content model in the project plan (§06):

- **Review packet** (§12.1): extractive-only, generated straight from `data/ranked/<iso-week>.json`, no dependency on drafting or verification.
- **Final digest**, generated only after a draft's entries are all `clear` or explicitly human-approved past a `flagged`/`blocked` state:
  - Output 1: `digest/<iso-week>.md` — ranked list, each entry: title (linked), source(s), score, the extractive excerpt, and the verified generative note.
  - Output 2: `site/index.html` — same content rendered as a simple static page (plain HTML + minimal CSS, no framework) for GitHub Pages. Include past weeks as an archive list.

## 15. GitHub Actions workflows

### 15.1 `.github/workflows/daily-ingest.yml`
- Trigger: `schedule: cron: '0 12 * * *'` (adjust to preferred UTC time) + `workflow_dispatch` for manual runs.
- Job matrix over the 5 connectors, each a separate matrix entry running its script with `pip install -r requirements.txt`. Each connector now also performs excerpt capture (§6) inline.
- Final job (`needs: [matrix job]`) commits new `data/raw/**` files back to the repo using `stefanzweifel/git-auto-commit-action` (free, widely used Action) or a plain `git commit && git push` step with the built-in `GITHUB_TOKEN`.

### 15.2 `.github/workflows/weekly-review-packet.yml`
- Trigger: `schedule: cron: '0 13 * * 1'` (Monday) + `workflow_dispatch`.
- Steps: `pipeline/dedup.py` → `pipeline/score.py` → `pipeline/filter.py` → `pipeline/render.py` (review-packet target only).
- Commit `data/ranked/**` and `digest/review/**` back to the repo.
- Final step: `pipeline/notify.py` sends an **internal notification** — "review packet ready for `<iso-week>`, N candidates" plus a link to the packet — via SMTP (Python `smtplib` + `ssl`) to the maintainer's own address. This is the same mechanism the Rev. 1 spec used for a subscriber-facing send; it's repurposed here per the project plan (§01, §05) because the actual subscriber send happens on Substack/Beehiiv, manually, and neither platform is reachable from this step. `DIGEST_RECIPIENT` is renamed `MAINTAINER_EMAIL` to make that scope explicit (§16).
- Does **not** deploy to Pages and does **not** touch `digest/<iso-week>.md` — those only exist after verification (§15.3).

### 15.3 `.github/workflows/weekly-verify-and-publish.yml`
- Trigger: `workflow_dispatch` only — run by hand once `digest/draft/<iso-week>.json` has been committed (i.e., once the maintainer's Claude-assisted drafting session is done).
- Steps: `pipeline/verify.py` → write `digest/verification/<iso-week>.json` → if every entry is `clear` (or has been hand-approved past a flag, tracked via a simple `approved: true` field the maintainer adds to a flagged/blocked entry before re-running), run `pipeline/render.py` (final-digest target) → commit `digest/<iso-week>.md`, `site/**` → deploy `site/` to GitHub Pages (`actions/deploy-pages` — free, official Action).
- If any entry is still `blocked` and unapproved, the job fails loudly rather than partially publishing — a compliance-adjacent newsletter shouldn't ship an issue with an unresolved citation or a vendor claim it couldn't verify.
- No email step here — sending to subscribers is the one manual, outside-of-CI step described in §3 and the project plan §05/§13.

## 16. Required GitHub Actions secrets

| Secret | Used by |
|---|---|
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | reddit.py |
| `GH_SEARCH_TOKEN` | github.py (search API rate limit) |
| `PRODUCTHUNT_TOKEN` | producthunt.py |
| `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `MAINTAINER_EMAIL` | weekly-review-packet.yml's internal notification step only — never a subscriber send |

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
- No auto-publishing to the newsletter platform — output is a curation and verification aid only; a human always pastes the final digest into Substack/Beehiiv and sends it.
- No unsupervised generative drafting — every "why this matters" note is written in a human/Claude-assisted session and gated by `verify.py` plus a bounded human checklist before it can ship (project plan §06). This is permanent, not a temporary safeguard to automate away later.
- No paid LLM API calls from CI — drafting happens interactively, not as a scripted call, so it never conflicts with the zero-budget constraint.
- No automated scoring-weight tuning off engagement data — reviewed by hand, quarterly, to avoid overfitting a filter to a small, noisy sample (project plan §05).
- No Twitter/X or LinkedIn connectors (no usable free API).
