# Weekly runbook

The single page for "what do I actually do this week." Everything here is
already specified in more depth elsewhere — `docs/technical-spec.md` for the
mechanics, `docs/project-plan.md` for the reasoning, and the three
`.claude/skills/` for step-by-step guidance during each session. This page
just puts the steps in order.

## The loop

| When | What happens | Who/what does it |
|---|---|---|
| Daily, automatic | `daily-ingest.yml` runs the four active connectors (hn, github, lobsters, producthunt — reddit deferred, see CHANGELOG.md), captures excerpts, commits `data/raw/**` | GitHub Actions |
| Monday, automatic | `weekly-review-packet.yml` dedups/scores/filters, renders `digest/review/<iso-week>.md`, opens a GitHub Issue that it's ready | GitHub Actions |
| Monday–Tuesday | Draft the issue: source-grounded notes, claims ledger, franchise tags, primary sources for Vendor Watch/Policy Corner | Maintainer + Claude, via the **`draft-digest`** skill |
| Once the draft is committed | Trigger `weekly-verify-and-publish.yml`, resolve any `blocked`/`flagged` entries, run the bounded checklist, approve | Maintainer, via the **`verify-and-ship-digest`** skill |
| Same session | Paste `digest/<iso-week>.md` into Beehiiv, confirm links, send | Maintainer (manual — no free publish API on the Launch tier) |
| Quarterly | Review reply/click data, propose small changes to `config/keywords.yml` or `pipeline/score.py`'s constants | Maintainer, via the **`tune-scoring`** skill |

## Time budget

- Drafting: no fixed budget — this is the actual writing, and quality here
  is the whole product.
- Verification + checklist: ~30–45 minutes.
- Paste and send: ~5 minutes.
- Pipeline maintenance (a connector breaks, an API changes): 1–2 hours, only
  in weeks it happens — not a steady cost.

If the verification + checklist step is regularly running well past 45
minutes, that's a signal the draft needs more work before verification, not
that the checklist should be shortened.

## What never gets skipped

- The bounded human checklist in `verify-and-ship-digest` — even when every
  automated check comes back `clear`. Automated checks catch broken links
  and invented citations; they don't catch a note that's technically
  accurate but misleading, or one whose tone doesn't fit.
- A `blocked` entry never ships. Fix the draft or drop the item — never
  edit `digest/verification/<iso-week>.json` to route around a block.
- Quarterly scoring review only happens on a real quarter's worth of
  pattern, never off a single standout week.

## When something breaks

- A connector failing: open an issue with the `connector-broken` template
  (`.github/ISSUE_TEMPLATE/connector-broken.md`) even if it's just for your
  own tracking — each connector is isolated, so one breaking doesn't block
  the rest of the week's ingest.
- A whole week with too little to say: skip it. The pipeline is built to
  make discovery cheap specifically so a quiet week costs nothing but a
  skipped Monday, not a rushed issue.
