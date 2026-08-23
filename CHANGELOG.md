# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/). This
project has no versioned releases yet — entries are dated instead, tracking
the project's pre-launch planning and scaffolding.

## Unreleased

### Added — table of contents, grouped by category
- Direct user request: the newsletter needed a table of contents, with
  items grouped by area/category and criticality (breaking news, new
  products, wow-factor, etc.), not a flat list. Added a required
  `category` field per item — `breaking | new_product | notable |
  field_notes` — deliberately separate from `franchise` (the recurring
  column format: Vendor Watch, Policy Corner, Reader Q&A); the two
  answer different questions and don't have to line up. Confirmed the
  category set and definitions with the user before implementing, since
  it's a taxonomy every future issue will reuse.
- `pipeline/render.py` builds one TOC block per issue in a fixed display
  order (breaking, new_product, notable, field_notes), omitting any
  category with no items that week rather than showing it empty. The
  markdown digest gets a grouped, readable (non-linked) list; `site/
  index.html` gets a real `<nav class="toc">` with working anchor
  links — each item's `<li>` now carries a stable `id="item-<cluster_id>"`
  for the TOC to jump to. New `.toc`/`.toc-group` CSS. `verify.py`
  doesn't check `category` — it's a classification, not a factual claim.
  Updated `docs/technical-spec.md` §12.2, `docs/editorial-guidelines.md`,
  the `draft-digest` skill and its `draft-schema.md` reference,
  `tests/test_render.py` (2 new tests, 2 existing tests fixed for the
  changed HTML structure), and retrofitted the live
  `digest/draft/2026-W34.json` with a category for each of its 7 items.

### Added — per-item `hook`: a one-sentence, plain-English reason to care
- User feedback on the W34 refresh: readers need to know why an item is
  worth their time — what's cool or useful about it — in plain English,
  before the longer, more skeptical `note` kicks in. `digest/draft/
  <iso-week>.json` items gained a required `hook` field, rendered
  immediately after the title and before the excerpt/note, in both
  `digest/<iso-week>.md` (bold line) and `site/index.html` (new
  `.item-hook` CSS class). Like `intro`, it isn't checked against the
  excerpt by `pipeline/verify.py` — it's a one-line framing, not a
  specific factual claim — but it must still be grounded only in the
  excerpt, usually as a tight paraphrase of the excerpt's own stated
  pitch. Updated `docs/technical-spec.md` §12.2, the `draft-digest` skill
  and its `draft-schema.md` reference, `tests/test_render.py` (3 new
  tests), and retrofitted the live `digest/draft/2026-W34.json` with a
  hook for each of its 7 items before re-publishing.

### Fixed — HN connector left raw HTML entities/tags in captured excerpts
- Found on the live site while reviewing the W34 refresh: the Hands item's
  excerpt showed the literal text `&#x2F;` instead of `/` (e.g. "CDP&#x2F;
  automation flags"). Root cause: `pipeline/excerpt.py`'s `capture_excerpt`
  used its `fallback_text` argument verbatim (just `.strip()`) instead of
  stripping it through BeautifulSoup like `hn_comment_fallback` already
  did — and HN's Algolia API returns `story_text` as raw HTML, literal
  `<p>` tags and HN's own `/` -> `&#x2F;` entity encoding included, not
  plain text. Left undecoded, `pipeline/render.py`'s `html.escape()` then
  double-escaped the leading `&` into `&amp;`, so a reader saw the literal
  entity string instead of `/`. Fixed by running `fallback_text` through
  the same `BeautifulSoup(...).get_text(" ", strip=True)` stripping —
  a safe no-op for the other 4 connectors, whose fallback text is already
  plain. Regression test added; verified the fix against the exact string
  captured from the real Hands item before shipping.

### Fixed — weekly-review-packet.yml computed the wrong ISO week
- Found by inspection while explaining the weekly cadence, before it ever
  shipped a broken packet for real: `pipeline.dedup`/`score`/`filter`
  defaulted to `iso_week_str()` = "now" when run with no `--iso-week`, and
  `weekly-review-packet.yml`'s cron fires Monday 13:00 UTC. Under ISO
  rules Monday is day 1 of a *new* week, so the scheduled run would have
  computed the week that had just started an hour earlier — not the week
  `daily-ingest.yml` spent the prior 7 days filling, which by Monday
  afternoon already belongs to the *previous* ISO week number. Every real
  run so far was a same-day manual `workflow_dispatch`, where "now" always
  happened to be the right week by coincidence, so this never surfaced.
- Added `--iso-week` to `pipeline/dedup.py` and `pipeline/score.py`
  (matching the flag `pipeline/render.py`/`verify.py` already had;
  `pipeline/filter.py` also gained it). `weekly-review-packet.yml` now
  computes yesterday's (Sunday's) ISO week explicitly in a `week` step and
  passes it to every stage — `dedup`, `score`, `filter`, `render
  --target review-packet`, and `notify` — instead of letting each one
  default to "now". Verified the CLI wiring end-to-end locally
  (`python -m pipeline.dedup --iso-week 2026-W34` etc.), then discarded
  the regenerated `data/ranked/`/`data/interim/` output rather than
  commit it — real pipeline output only ships from an actual CI run.

### Changed — 2026-08-23: loosened the relevance filter's AND-requirement
- User asked why nothing outside Product Hunt was ever clearing the
  relevance bar. Investigated against the real, current day's pull
  (345 items: 50 GitHub, 111 HN, 5 Lobsters, 179 Product Hunt): 49/111 HN
  items mentioned a `core_terms` AI-coding tool (Copilot, Cursor, Claude
  Code, ...) but **zero** also mentioned a `context_terms` fintech/
  compliance word in the same title+excerpt text — same for GitHub (5
  core hits, 9 context hits, 0 overlap). The `core AND context` rule is a
  poor fit for how HN/GitHub titles are actually phrased: they're terse
  and rarely spell out the regulated-industry angle explicitly even when
  the story is a genuinely good fit (e.g. a Copilot CVE, or a self-hosted
  AI trading OS that keeps credentials off a vendor's cloud). The
  existing "hot story" bypass (2+ core terms, top-decile velocity) didn't
  help either — HN's engagement metric runs orders of magnitude cooler
  than Product Hunt's vote counts on a given day, so the 4 HN items that
  did hit 2+ core terms had velocity scores of 0.001–0.067 against a 4.79
  top-decile threshold.
- `pipeline/filter.py`: `passes_filter` now accepts a single `core_terms`
  hit (was 2+) gated by `_velocity_threshold`'s default percentile, which
  moved from top-decile (0.1) to top-quartile (0.25) — `core AND context`
  is still an automatic, velocity-independent pass. Simulated against the
  real pull above before committing: old rule passed 4 items (all
  Product Hunt); new rule passes 25 (4 GitHub, 15 HN, 6 Product Hunt).
  Recorded here per `config/keywords.yml`'s own instruction not to
  hand-edit outside a quarterly review without a reason on file. This is
  a filter/ranking change, not an editorial one — the human curator in
  `draft-digest` still decides what actually ships, so a broader ranked
  pool only changes what material is available to choose from.

### Added — issue intro (connective narrative at the top of each issue)
- Real user feedback on the first live issue: three isolated per-item
  summaries with no frame or synthesis read as a bare link list, not a
  newsletter — "no introductory narrative, no fun jokes, no substance
  beyond summarizing three products." Investigated the content side
  separately: re-ran `dedup`/`score`/`filter` against that week's real
  345-item pull and confirmed only 4 clusters (all Product Hunt) passed
  the relevance filter — a genuine single-day, single-source data
  characteristic, not a drafting failure, and not something to paper
  over by inventing content.
- `digest/draft/<iso-week>.json` schema changed from a bare array to
  `{"intro": ..., "items": [...]}` — `intro` is a short connective
  narrative for the whole issue, optional (empty string is valid),
  voice is "dry wit, still professional" per the user's explicit choice.
  It is not a per-item factual claim, so `pipeline/verify.py` does not
  check it against any excerpt or claims ledger, but it still must not
  invent specifics not grounded in the items it introduces.
  `pipeline/render.py` renders it once, at the top of the issue, in both
  `digest/<iso-week>.md` and `site/index.html` (new `.issue-intro` CSS
  rule). Updated `docs/technical-spec.md` §12.2,
  `docs/editorial-guidelines.md` (Voice, Formats), the `draft-digest`
  skill and its `draft-schema.md` reference, and all fixture data in
  `tests/test_render.py` (3 new tests). Migrated the real, already-shipped
  `digest/draft/2026-W34.json` to the new schema with an actual intro
  written from its 3 real items' excerpts — including being upfront in
  the intro itself about the single-source week, rather than hiding it.

### Fixed — public site was missing the actual newsletter content
- `site/index.html` rendered only a bare linked title per item — the
  excerpt and the drafted "why this matters" note (the entire point of the
  newsletter) went into `digest/<iso-week>.md` but never reached the
  public page, despite `docs/technical-spec.md` §14 saying the site gets
  "the same content." Present since the pipeline was first built; not
  caught by any test, because no test asserted this content reached the
  site specifically — found by the user looking at the real deployed page
  after the first real issue went live. `_render_archive_item_html` now
  renders each item's excerpt (as a blockquote), note, a franchise-tag
  badge for non-weekly franchises, and a primary-source link when present
  — matching `digest/<iso-week>.md`'s structure. Six new tests assert this
  content actually reaches `site/index.html`, not just the digest file.
- That fix required touching the idempotent-replace logic again: items now
  nest their own `<blockquote>`/`<p>` markup, so the existing `</ul></li>`
  structural terminator (from the earlier duplication fix) could match an
  inner tag sequence instead of the block's real end. Replaced with a
  matched pair of `<!-- week:<iso-week> -->` / `<!-- /week:<iso-week> -->`
  HTML-comment markers, which can't be confused with structural HTML at
  any nesting depth. Verified locally in a real browser (screenshot-level
  check, not just HTML-string assertions) before shipping, and added a
  regression test that re-renders three times with rich nested content to
  confirm the boundary detection still holds.

### Fixed — non-fast-forward push race between weekly-verify-and-publish.yml's two jobs
- With both prior bugs fixed, `verify` passed clean for real — but
  `render-and-deploy`'s own commit push was then rejected: `! [rejected]
  main -> main (non-fast-forward)`. Checked the actual commit history
  before assuming a cause: no other author pushed in that window, so this
  wasn't a collision with the other concurrent session — it was the same
  workflow run's own two jobs racing each other on `main` roughly 10
  seconds apart (`render-and-deploy`'s checkout landed just behind
  `verify`'s own commit-and-push a moment earlier). Added `git pull
  --rebase origin main` immediately before `render-and-deploy`'s commit
  step, rather than trust a job-start checkout stays current through
  everything that job does before it pushes. That fix's first real run
  then failed differently: "cannot pull with rebase: you have unstaged
  changes" — `pipeline.render` had already written uncommitted digest/site
  changes to the working tree earlier in the same job, and a plain
  `git pull --rebase` refuses to run against a dirty tree at all. Added
  `--autostash` so the pull stashes those uncommitted changes, rebases,
  and reapplies them before the commit step runs.

### Fixed — two real verify.py bugs, found on the pipeline's first real drafted issue
- **False-positive claim flags on verbatim quotes.** Drafted `digest/draft/
  2026-W34.json` (three source-grounded items) and ran real verification —
  3 of 9 claims got flagged as "unsupported" despite `supported_by` being
  an exact, verbatim substring of the stored excerpt. Root cause:
  `_fuzzy_contains`'s sliding window padded every comparison chunk with a
  fixed +20 characters. Since `SequenceMatcher.ratio() = 2*M/(len(a)+len(b))`,
  that padding mathematically caps the achievable ratio for a perfect match
  (~0.836 for a 51-character claim) *below* the 0.85 threshold, regardless
  of match quality — and shorter, more precisely quoted claims were
  paradoxically the ones most likely to get wrongly flagged. Fixed with an
  exact-substring short-circuit before any fuzzy scoring, and a window
  sized to the claim itself instead of claim-length-plus-a-constant.
- **False `blocked` on bot-protected but real links.** All three drafted
  items link to producthunt.com, which 403s every automated request —
  confirmed live with `curl`, default headers and a full realistic browser
  header set alike — serving a Cloudflare "Just a moment..." JS challenge
  (`cf-mitigated: challenge`). No HTTP-only client can ever pass that, so
  treating it as a confirmed-dead link would have permanently hard-blocked
  every Product Hunt-sourced item, forever. `check_link` now returns a
  three-state status (`ok`/`dead`/`unverifiable`) instead of a bool;
  bot-challenge signatures downgrade an entry to `flagged` rather than
  `blocked`. Verified this doesn't just paper over real failures: a plain
  403 with no Cloudflare signature is still `dead`. Closed the loop
  properly rather than just trusting the theory — used Claude-in-Chrome to
  actually load all three producthunt.com URLs in a real browser (which
  passes the JS challenge fine) and confirmed each page's title matches
  the drafted item exactly, then marked all three `approved: true` in the
  draft with that reasoning, per the documented flagged-claim process.

### Changed — Gmail SMTP replaced with a GitHub Issue
- `pipeline/notify.py` no longer sends email at all. A Gmail app password is
  real setup friction (2FA prerequisite, a Google-account-specific manual
  step) for a notification GitHub can already deliver for free. It now
  opens a GitHub Issue — "Review packet ready: `<iso-week>`" with the
  candidate count and a link to the review packet — using the `GITHUB_TOKEN`
  every Actions run already gets, gated by an explicit `issues: write`
  permission on the job (no repo secret to configure at all). GitHub's own
  notification system pings the repo owner exactly the way the SMTP step
  used to. Idempotent the same way the site archive fix was: searches for
  an existing open issue with this week's exact title before opening a new
  one, so a re-run never duplicates the notification. Confirmed against the
  real API (opened and closed a real test issue on the live repo) before
  adopting it, not assumed. `GMAIL_ADDRESS`/`GMAIL_APP_PASSWORD`/
  `MAINTAINER_EMAIL` are gone from `.env.example`, the secrets table, and
  the workflow; `docs/project-plan.md`'s cost table and `docs/weekly-
  runbook.md` updated to match.

### Changed — GitHub star velocity replaced with log-scaled total stars
- Found on the same real run above: with a valid `GH_SEARCH_TOKEN`, every
  one of 49 stargazers-endpoint calls returned `404`, not the `401` seen
  earlier without a token. Isolated it live with a separate, fully-scoped
  token: `repos/torvalds/linux/stargazers` and
  `repos/octocat/Hello-World/stargazers` both `404`; `repos/roberjo/
  guardrail-radar/stargazers` (a repo that token's own account owns)
  succeeds. This is GitHub restricting third-party stargazer-timestamp
  enumeration outright, not a scope or auth problem — no token, however
  broadly scoped, gets `stars_last_7d` for a repo the token holder doesn't
  own. The original §7.3 design (`stars_last_7d` via `starred_at`
  timestamps) is no longer achievable through this API.
  `connectors/github.py` now uses `raw_score = int(math.log1p
  (stargazers_count) * 100)` — the search endpoint already returns total
  star count for free, so this also removes the 49 now-always-failing
  per-repo calls entirely. The log scale matters, not just the fallback
  metric choice: total stars for a popular repo can be in the hundreds of
  thousands, versus HN points or Reddit ups typically in the dozens to
  low thousands — feeding that raw into the shared velocity formula
  (`pipeline/score.py`) would let one popular repo's routine push swamp
  every other source's ranking. The log scale keeps it monotonic (more
  stars still ranks higher) while compressing it into a comparable
  magnitude (250,000 stars → ~1,151, not 250,000). Raw `total_stars` is
  still kept in `source_meta` for reference. `docs/technical-spec.md` §7.3
  updated to match; this is a real, permanent capability loss, not a bug
  to route around later.

### Fixed — first real daily-ingest.yml run, found by actually running it
- All four active connectors (hn, github, lobsters, producthunt) succeeded
  and pulled real data (6,274 lines across 4 files) on the first live run
  against real GitHub Actions infrastructure with real credentials — but
  the `commit` job's push back to the repo 403'd: `git-auto-commit-action`
  built the commit locally, then failed with "Permission to
  roberjo/guardrail-radar.git denied to github-actions[bot]". Neither
  `daily-ingest.yml` nor `weekly-review-packet.yml` declared a `permissions:`
  block, so their default `GITHUB_TOKEN` was read-only — only
  `weekly-verify-and-publish.yml` had one, added earlier this session and
  never actually exercised until now. Both now declare `contents: write`,
  scoped to just the job that commits (the connector matrix itself never
  needs write access). Confirmed by re-running daily-ingest.yml for real
  after the fix — see the next entry for the result.

### Changed — Reddit deferred
- Reddit script-app creation is currently blocked for the project's Reddit
  account, ruling out the OAuth path `connectors/reddit.py` was built
  against. Before deferring, tried the common fallback of Reddit's public
  `.json` endpoints (no auth) — both `www.reddit.com` and `old.reddit.com`
  return `403` with an explicit "blocked by network security" page,
  regardless of User-Agent. Confirmed this isn't a local-network fluke by
  pushing a temporary `workflow_dispatch` probe and running it for real on
  a GitHub Actions runner: same `403`s from that IP range too, meaning
  Reddit is blocking the shared runner IPs outright, not just this one
  sandbox. `reddit` removed from `daily-ingest.yml`'s connector matrix
  (four connectors run daily now: hn, github, lobsters, producthunt) so it
  isn't a guaranteed-failing scheduled job — `connectors/reddit.py` and its
  test coverage are otherwise untouched, and re-adding it is a one-line
  matrix change once a working credential path exists. Consistent with the
  architecture's own design: each connector is isolated specifically so one
  source being unavailable doesn't block the rest (`docs/technical-spec.md`
  §3).

### Added — mypy, made real
- A concurrent session's changelog entry claimed "ruff and mypy clean on
  touched files," but mypy wasn't installed, configured, or run anywhere in
  the repo — an unreproducible claim. Running it turned up two genuine
  findings, not just type-checker noise: `connectors/github.py` passed a
  possibly-`None` `html_url` straight into `NormalizedItem`/
  `capture_excerpt` (both require `str`) with no guard — now skipped with a
  logged warning instead of risking an `AttributeError` deep inside
  `canonicalize_url` on the rare response missing that field, consistent
  with the project's existing skip-and-log pattern for malformed data.
  `pipeline/excerpt.py`'s `<meta>`-tag extraction relied on BeautifulSoup's
  `.find()` possibly returning a `NavigableString` (no `.get()`) or a
  multi-valued attribute (`list[str]`, not `str`) — neither happens for a
  real `<meta>` tag in practice, but a new `_meta_content` helper narrows
  both explicitly rather than assuming it. `mypy`, `types-requests`,
  `types-PyYAML`, `types-beautifulsoup4` added to `requirements-dev.txt`,
  config in `pyproject.toml`, and `mypy connectors pipeline` now runs in
  `test.yml` — the claim is enforced in CI, not just asserted in prose.

### Fixed
- `connectors/github.py`'s `_readme_first_paragraph` used `.lstrip("#")` on
  a heading line, returning the bare title text ("Project Title") as if it
  were the README's first paragraph — since virtually every README opens
  with a `# Title` heading, this meant the fallback excerpt was the repo
  name repeated, not a description, on effectively every repo. Found by a
  test using a realistic "heading, then badge, then real paragraph" shape;
  now headings are skipped entirely rather than stripped-and-kept.

### Reconciled with concurrent work
- Another session was independently improving `connectors/reddit.py` and
  `connectors/producthunt.py` at the same time (this repo has no git yet,
  so no branch isolation between us) — real, complementary improvements:
  `raw_json=1` on Reddit listing requests (avoids double-HTML-escaped
  entities), filtering `[removed]`/`[deleted]` selftext so it's never used
  as excerpt fallback text (directly on-mission for the anti-hallucination
  design — a removed post's body is not a real excerpt), a proper
  comment-fallback for Reddit link posts, and switching Product Hunt to
  per-topic server-side GraphQL queries instead of unfiltered
  client-side filtering. Their own test additions covered these; I only
  needed to remove two of my own now-stale assertions in
  `tests/test_reddit.py` that conflicted with the corrected behavior.

### Fixed (found by a third independent `reviewer` agent pass, closing the citation/URL-scoping gaps left by the second pass)
- `pipeline/verify.py`'s citation check confirmed a cited `cluster_id`
  existed but never confirmed the draft entry's own `url` actually matched
  that cluster's `url` — an entry could cite a real, valid `cluster_id`
  (passing the citation check) while its own headline/link pointed at a
  different story than the one its claims were checked against. Now blocks
  on a mismatch. Per §12.2, `title` is the one field a human is expected to
  lightly edit during drafting, so only `url` is enforced strictly.
- `pipeline/verify.py`'s `primary_source_url` link-check was gated to only
  `vendor_watch`/`policy_corner` franchises, so any other franchise could
  carry an arbitrary, never-link-checked `primary_source_url` into the
  published digest. Per §13.1 ("every url and primary_source_url in the
  draft" gets link-checked), the check now runs for any franchise where the
  field is present; the *requirement* that it be present at all stays
  scoped to those two franchises, per §13.4.
- `pipeline/render.py` had no scheme restriction on the URL it renders
  (`entry.get("url") or cluster.get("url", "")`), so a human overriding a
  blocked entry with `approved: true` could fall through to an unchecked
  `cluster.get("url")` and, in principle, put a non-http(s)-scheme URL into
  a clickable archive link — `html.escape()` neutralizes markup but not
  URL schemes. Now restricted to `http`/`https`; anything else renders the
  title as plain text with a stderr warning instead of a link.
- `pipeline/render.py` interpolated `entry['primary_source_url']` into the
  final digest unescaped, unlike every other piece of third-party-sourced
  text in the same function — now passed through the existing `_md_escape`.
- `pipeline/render.py`'s review-packet markdown links escaped the title but
  not the URL, so a `)` in a URL could prematurely close the markdown link
  and leak trailing URL text as stray content. URLs are now defensively
  percent-encoded for `)` before being placed in a link target.
- Total suite: 127 tests, all passing; ruff and mypy clean on touched files.

### Fixed (found by a second independent `reviewer` agent pass over `pipeline/`)
- `pipeline/verify.py`'s claims-ledger check — the core anti-hallucination
  gate — only ever confirmed a claim's `supported_by` quote existed
  somewhere in the excerpt; it never checked that the claim's own `text`
  was actually grounded in that quote. A real, verbatim excerpt quote could
  be paired with an unrelated or contradictory `text` and still pass as
  `clear`. Compounded by `_fuzzy_contains`'s pure character-similarity
  match, which scored a quote with a single digit swapped (e.g. "20%" for
  "80%") at ~0.99 against the real excerpt — well past the 0.5 threshold.
  Fixed with a raised match bar for `supported_by`-vs-excerpt, an explicit
  check that any numeric tokens in `supported_by` appear verbatim in the
  excerpt, and a term-overlap check between `claim["text"]` and
  `supported_by` so a claim about a different subject than its own citation
  is now flagged. Regression tests added for both failure modes.
- `pipeline/filter.py` + `pipeline/score.py` — the cluster representative
  (the item whose title/url/source get published for a cross-source story)
  was never actually chosen by engagement. `score.py` assigns one uniform
  `cluster_score` to every item in a cluster, so `filter.py`'s
  best-scoring-item comparison never fired past the first item in list
  order — which came from an alphabetical glob of `data/raw/*/*.json`
  (`github` < `hn` < `lobsters` < `producthunt` < `reddit`). A low-engagement
  GitHub listing would always win over a substantive HN/Reddit discussion of
  the same story. Existing tests didn't catch this because they hand-set
  differing `cluster_score` values per item within a cluster — something
  `score.py` could never actually produce. Fixed by using each item's
  individual `item_score` (already computed, just never consumed) for the
  representative-selection comparison; `cluster_score` is unchanged for
  final ranking. New test runs real `score_items` output through
  `filter_and_rank` to confirm the higher-engagement item now wins
  regardless of source name.
- `pipeline/dedup.py` and `pipeline/score.py` had no per-item fault
  isolation — a single malformed item from any one connector (missing
  `title`, unparsable `posted_at`) raised an uncaught `KeyError`/`ValueError`
  that aborted clustering/scoring for the entire week's batch across all
  five sources. Now skipped with a stderr warning, matching the connectors'
  own failure-logging convention.
- `pipeline/notify.py` silently reported "0 candidates ranked" and still
  sent the "review packet ready" email when `data/ranked/<iso-week>.json`
  didn't exist (e.g. a wrong `--iso-week` or an earlier crashed stage),
  pointing the maintainer at a review packet that was never generated.
  Now raises `FileNotFoundError` instead of sending a misleading email.
- Total suite: 122 tests, all passing; ruff and mypy clean on touched files.

### Added — test coverage for previously-untested modules
- `tests/test_hn.py`, `tests/test_lobsters.py`, `tests/test_github.py` —
  the three no-auth connectors were only ever live/manually tested, not
  covered by the permanent suite. Includes a regression test for the
  GitHub star+json-needs-auth bug (already fixed) degrading gracefully
  rather than crashing.
- `tests/test_render.py` (12 tests) — including a permanent regression test
  for the site-archive idempotency bug below: renders the same week three
  times and asserts exactly one well-formed archive entry results. Also
  covers the review-packet/final-digest content, the refuse-to-render-while-
  blocked gate, the approved-override path, and HTML/Markdown escaping of
  untrusted titles and URLs.
- `tests/test_io_utils.py` (5 tests) and `tests/test_notify.py` (2 tests) —
  closed the last remaining zero-coverage modules; `notify` is tested with
  `smtplib.SMTP_SSL` mocked, confirming it only ever addresses the
  maintainer (no Cc/Bcc, no subscriber recipient).
- Total suite: 84 tests, all passing; lint and compile clean.

### Fixed (found by an independent `reviewer` agent pass, each confirmed by reproduction)
- `pipeline/render.py`'s site-archive update duplicated a week's `<li>` on
  every re-run instead of replacing it — confirmed by actually re-running
  `render --target final-digest` twice against the same week. Fixed with a
  `data-week` attribute per entry and a targeted find-and-replace; the first
  fix attempt used a regex that stopped at the first *inner* story's `</li>`
  instead of the block's own close, corrupting the HTML on a second run —
  caught by re-reproducing the same scenario after the fix, not assumed
  correct. Verified clean after three consecutive re-renders of the same
  week, parsed with BeautifulSoup to confirm valid structure, and confirmed
  two different weeks coexist correctly.
- `.github/workflows/daily-ingest.yml` uploaded each connector's artifact as
  `raw-<source>` but the layout requires `data/raw/<source>/`, not
  `data/raw/raw-<source>/` — `actions/download-artifact` extracts by
  artifact name, so the name now matches `matrix.source` exactly.
- `.github/workflows/weekly-verify-and-publish.yml` ran `pipeline.verify`
  twice (once bare, once with `--assert-clear`) — doubled live link-check
  traffic against every URL in the draft for no reason, and meant the
  committed verification file only reflected whichever run happened to run
  last. Now a single `--assert-clear` run.
- Same workflow: the commit step for `digest/verification/**` had no
  `if: always()`, so on the one run that matters most for a human to see
  (something got blocked, `pipeline.verify` exits non-zero) the step after
  it — the one that commits the verification results — was silently skipped
  by GitHub Actions' default failed-step behavior.
- `connectors/producthunt.py`'s excerpt fallback joined the *entire*
  description, not "the first paragraph" per §8.2 — could crowd out the
  tagline or cut off mid-sentence once truncated to 1000 chars.
- `pytest` was in `requirements.txt`, meaning all three scheduled/production
  workflows installed it, not just `test.yml`. Split into
  `requirements-dev.txt` (adds `pytest`, `ruff`); `test.yml` and local-dev
  docs updated accordingly.
- `connectors/reddit.py` and `connectors/producthunt.py`'s docstrings
  claimed mocked-test coverage in `tests/test_reddit.py` /
  `tests/test_producthunt.py` — neither file existed. Both now do (14 new
  tests covering the pure helpers and `fetch_items` end-to-end against a
  mocked Session, including Reddit's dedup-across-listings and Product
  Hunt's pagination and topic filter).

### Implemented
- All five connectors (`connectors/hn.py`, `reddit.py`, `github.py`,
  `lobsters.py`, `producthunt.py`) and the full `pipeline/` (`schema`,
  `excerpt`, `dedup`, `score`, `filter`, `verify`, `render`, `notify`),
  replacing the earlier stubs.
- `pipeline/io_utils.py` — shared JSON/date helpers, added to avoid five
  connectors re-deriving the same logic (not in the original §4 sketch).
- `data/interim/<iso-week>.json` — the shared working file between
  `pipeline.dedup`, `pipeline.score`, and `pipeline.filter` (§9).
- Real unit tests for `schema`, `dedup`, `score`, `filter`, `excerpt`, and
  `verify` (51 tests), replacing the stub test files. All network calls in
  tests are mocked — no live requests in CI.
- SSRF hardening in `pipeline/excerpt.py` and `pipeline/verify.py`: both
  resolve the target hostname and refuse private/loopback/link-local
  addresses before making a request, since both fetch arbitrary third-party
  URLs sourced from Reddit/HN/GitHub/etc.
- HTML/Markdown escaping of third-party titles and excerpts in
  `pipeline/render.py` — this content is untrusted input.

### Verified by live testing
- `connectors/hn.py` and `connectors/lobsters.py` against the real APIs
  (no auth required) — excerpt capture succeeded for ~97% of a live HN pull
  (86 ok / 21 partial / 3 none out of 110 items).
- `connectors/github.py` against the real API, unauthenticated.
- The full draft → verify → render loop, using a synthetic fixture with one
  clean entry and three deliberate failures (missing primary source for
  `vendor_watch`, a dead link paired with a fabricated statistic, and an
  invented citation not present in `data/ranked`) — `pipeline/verify.py`
  correctly caught all three, and `pipeline/render.py` correctly refused to
  render the final digest until they were resolved.
- `connectors/reddit.py` and `connectors/producthunt.py` are implemented per
  spec but require credentials this environment doesn't have — verified via
  mocked unit tests only, not a live run. Confirm against real credentials
  before the first production week.

### Fixed (found via the live-test loop above)
- GitHub's `star+json` media type 401s even for public repos when
  unauthenticated — `connectors/github.py` now skips `stars_last_7d` lookups
  entirely (rather than failing per-repo) when `GH_SEARCH_TOKEN` isn't set.
- `BeautifulSoup.get_text(strip=True)` was concatenating words across inline
  tags with no separator (`"a <i>real</i> comment"` → `"arealcomment"`) in
  both `pipeline/excerpt.py`'s paragraph fallback and its HN comment
  fallback — now uses `get_text(" ", strip=True)`.

### Added
- Full repository scaffold matching `docs/technical-spec.md`: `connectors/`,
  `pipeline/`, `config/`, `data/`, `digest/`, `site/`, `tests/`, and the
  three GitHub Actions workflows — all as stubs/placeholders pending the
  build described in the spec's §19 build order.
- `README.md`, `LICENSE` (MIT), `CONTRIBUTING.md`, `.gitignore`,
  `.env.example`.
- `docs/weekly-runbook.md` — the single-page operational loop tying the
  three `.claude/skills/` and the three workflows together.
- `docs/editorial-guidelines.md` — standalone voice/format/integrity
  reference, consolidating what was previously scattered across the project
  plan and the skill files.
- `.claude/skills/draft-digest`, `.claude/skills/verify-and-ship-digest`,
  `.claude/skills/tune-scoring` — structured guidance for the three
  recurring human-in-the-loop steps in the pipeline.
- `.github/ISSUE_TEMPLATE/connector-broken.md`.

### Changed
- Moved `research-pipeline-spec.md` and `guardrail-radar-project-plan.md` to
  `docs/technical-spec.md` and `docs/project-plan.md`, keeping the root
  focused on entry-point files (`README.md`, `LICENSE`, etc.).
- `docs/technical-spec.md` revised to Rev. 2: added excerpt capture (§6), a
  review-packet/draft handoff (§12), an automated verification stage
  (§13), and `pipeline/notify.py` as the module behind the repurposed
  internal-notification email step (§15.2). See the spec's own revision
  note for the full list.

## Earlier (pre-changelog)
- Initial technical build spec drafted (`research-pipeline-spec.md`, since
  moved — see above).
- Full project plan drafted (`guardrail-radar-project-plan.md`, since
  moved — see above): audience, business plan, marketing, finance, legal,
  risk, and roadmap.
