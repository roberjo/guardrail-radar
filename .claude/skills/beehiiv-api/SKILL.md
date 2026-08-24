---
name: beehiiv-api
description: This skill should be used when the user asks to "check Beehiiv", "check the publication settings", "pull subscriber/analytics data", "push a draft to Beehiiv", "create a Beehiiv draft post", or wants to read from or write to the Guardrail Radar Beehiiv account via pipeline/beehiiv.py. Covers what's safe to automate (reads, draft creation) and what stays a manual human action (sending).
version: 0.1.0
---

# Beehiiv API

`pipeline/beehiiv.py` is a thin client for Beehiiv's API v2, scoped to this
project's publication. It exists to remove *reading* and *drafting* friction
from the weekly cycle — it must never remove the human send step. That step
stays manual by deliberate design (see `docs/weekly-runbook.md` and the
`verify-and-ship-digest` skill's Step 6) for the same reason `verify.py`'s
claims-ledger check exists at all: a wrong or unreviewed issue reaching a
real subscriber costs more than a slower publish.

## The one rule that matters more than anything else here

**Nothing in this integration may cause a post to be sent or set to
`confirmed`/live status.** `create_draft_post` in `pipeline/beehiiv.py`
hardcodes `"status": "draft"` on every call, then polls the created post
and hard-fails (raises `BeehiivError`) if the final status isn't actually
`"draft"` — belt-and-suspenders, because Beehiiv's Create Post endpoint
publishes immediately to all free subscribers by default when `status` is
omitted (this changed 2026-08-06 to default-to-draft, but the code never
relies on that platform-side default — see
`references/api-reference.md`). Do not add a function that can transition a
post out of draft, and do not call Beehiiv's separate Send API from this
project. If you're ever asked to build actual automated sending, that's a
deliberate scope change to flag explicitly to the user first, not something
to infer from "the API supports it."

## Beehiiv's official MCP server (added 2026-08-24, separate from the above)

`claude mcp add --transport http beehiiv https://mcp.beehiiv.com/mcp` was
run for this project (local config, private to the maintainer). It's not
connected until the maintainer runs `claude mcp login beehiiv` themselves
in an interactive terminal — that login can't be completed from a
background/non-interactive session, since it opens a local OAuth callback
listener. The authorization request asked for `scope=read+write`, so once
connected its tools can very plausibly do more than `pipeline/beehiiv.py`
does today — possibly including actions equivalent to publishing or
sending, not just drafting.

**The same rule applies regardless of which path is used.** If the
Beehiiv MCP's tools are ever used instead of `pipeline/beehiiv.py`, the
"never cause a post to be sent or go live without the user explicitly
asking for that specific action" rule above still holds — check what an
MCP tool actually does (its description, and its parameters like a
status/publish field) before calling it, the same way `create_draft_post`
was written only after confirming Beehiiv's real status-field behavior,
not by assuming a tool named e.g. "create_post" defaults to safe.

## Credentials

Two env vars, both already in `.env` locally (never in git — see
`.gitignore` and `.env.example`):

- `BEEHIIV_API_KEY` — the real secret. Generated in the Beehiiv dashboard:
  Settings → Workspace Settings → API → Create New API Key. Requires
  Owner/Admin role and (per Beehiiv) completed Stripe Identity
  Verification before the API section is even usable.
- `BEEHIIV_PUB_API_KEY` — **not actually a secret**, despite the name (that
  naming is the maintainer's own choice, not this project's convention) —
  it's the publication id (`pub_ce3a249a-ebd9-4d23-8c43-1ca597987269`),
  visible in the dashboard URL and every API response. `PUBLICATION_ID` in
  `pipeline/beehiiv.py` reads this env var and falls back to that literal
  value if unset.

Never print, log, or paste the value of `BEEHIIV_API_KEY` anywhere —
chat included. If you need to confirm it's set, check presence/length only
(see the pattern used when this was first debugged: a `pub_...`-shaped
value had been pasted into `BEEHIIV_API_KEY` by mistake, caught by checking
the value's shape, not its content).

## What's implemented (`pipeline/beehiiv.py`)

| Function | What it does | Side effect |
|---|---|---|
| `get_publication(expand_stats=True)` | Publication name, org, and (with stats) subscriber counts + open/click rates | None — read-only |
| `list_posts(limit=10, status="all")` | Recent posts, optionally filtered by status | None — read-only |
| `get_post(post_id)` | One post's full detail; handles Beehiiv's async-creation `202` and `POST_CREATION_FAILED` states | None — read-only |
| `create_draft_post(title, body_content, subtitle="")` | Creates a post, forced to `status="draft"`, polls until creation finishes, verifies the final status | **Writes** — creates a real draft in the dashboard |
| `push_draft(iso_week)` | Builds this week's issue via `pipeline.render.build_beehiiv_draft_content` and calls `create_draft_post` | **Writes** — same as above |

CLI: `python -m pipeline.beehiiv --action {publication,posts,push-draft} [--iso-week YYYY-Www]`.

The draft body itself comes from `build_beehiiv_draft_content(iso_week)` in
`pipeline/render.py` — same draft/ranked data and hotness ordering as
`render_final_digest`, same `_assert_no_unresolved_blocked` safety gate, but
rendered as self-contained inline-styled HTML instead of the site's
class-based CSS (Beehiiv's editor can't load `ISSUE_PAGE_CSS`) and without
`<details>` (unreliable outside this project's own pages — same reason
`digest/<iso-week>.md` avoids it).

## Workflow

1. **Read-only checks** (`get_publication`, `list_posts`) — safe to run any
   time, no confirmation needed beyond the general norm of not spamming the
   API.
2. **Preview before creating anything.** Call
   `pipeline.render.build_beehiiv_draft_content(iso_week)` directly and look
   at the output (or render it to a local HTML file) before calling
   `create_draft_post`/`push_draft` — confirmed working this way the first
   time this was built, catching formatting issues before anything touched
   the real account.
3. **Creating a draft post is a write to the user's real Beehiiv account.**
   Confirm with the user before calling `push_draft`/`create_draft_post`,
   same as any other "changing account settings" action — one confirmation
   covers that one call, not a standing approval for future weeks.
4. **After a draft is created**, the human still reviews and sends it by
   hand in the Beehiiv dashboard — this integration only removes the
   copy-paste step, not the review step.

## Known gaps / open questions

- **Publication settings can't be updated via the API at all** — confirmed
  2026-08-24, the Publications section of the API is list/show only, no
  write endpoint exists (see `references/api-reference.md`). Any
  name/branding/settings fix has to happen by hand in the dashboard (this
  is how a "Guardrail-radar" vs. "Guardrail Radar" name mismatch found the
  same day got fixed).
- Whether Launch-tier API access covers subscriber-list/segment endpoints
  hasn't been checked — confirm against real docs before building anything
  that assumes it does.
