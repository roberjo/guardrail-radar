---
name: verify-and-ship-digest
description: This skill should be used when the user asks to "verify this week's digest", "run the digest checklist", "check the draft before sending", "publish this week's issue", "ship the newsletter", or wants to move a completed digest/draft/<iso-week>.json through verification to a sent issue. Walks through pipeline/verify.py's output and the bounded human approval checklist before publishing to Substack/Beehiiv.
version: 0.1.0
---

# Verify and Ship Digest

Gate a drafted issue before it reaches subscribers. This is the one
mandatory human checkpoint in the Guardrail Radar pipeline
(`research-pipeline-spec.md` §13; project playbook §06) — never skip it,
even when every automated check comes back clean, and never rush it under
deadline pressure. A wrong claim reaching this audience costs more than a
late issue.

## Prerequisite

`digest/draft/<iso-week>.json` must already exist and be committed — produced
by the `draft-digest` skill. This skill does not draft content, only
verifies and ships it.

## Step 1 — Run verification

Trigger `.github/workflows/weekly-verify-and-publish.yml` (`workflow_dispatch`)
against the committed draft, or run `pipeline/verify.py` locally against the
same `digest/draft/<iso-week>.json` and `data/ranked/<iso-week>.json`. Read
the resulting `digest/verification/<iso-week>.json` — each entry is marked
`clear`, `flagged`, or `blocked`.

## Step 2 — Resolve every `blocked` entry

A `blocked` status is a hard stop, not a suggestion:

- A `cluster_id` that doesn't resolve against `data/ranked/<iso-week>.json`
  means the item may be misremembered or invented — verify it actually
  exists in that week's ranked data before doing anything else.
- A dead link, unexpected redirect, or timeout on `url` or
  `primary_source_url` must be fixed at the source (find the correct link)
  or the item dropped.
- A `vendor_watch`/`policy_corner` entry missing a working
  `primary_source_url` must get one added or be dropped — never invent or
  substitute a secondary source to satisfy this check.

Fix the draft and rerun verification. Never resolve a block by editing
`digest/verification/<iso-week>.json` directly — the fix always happens in
the draft.

## Step 3 — Work through every `flagged` claim

A flag means the fuzzy-match couldn't confirm a claim's `supported_by` text
against the stored excerpt — it is a signal to re-check by hand, not proof
the claim is wrong. For each flagged claim:

1. Re-read the excerpt (and the original source URL if the excerpt is
   ambiguous).
2. If the note overstates or misreads the excerpt, rewrite the note's
   wording to match what the source actually supports.
3. If the claim is in fact correct and the flag is a false positive (loose
   paraphrase, formatting difference), add `"approved": true` and a one-line
   reason to that entry before rerunning verification.

## Step 4 — Run the bounded checklist, on every entry, regardless of status

This runs even on entries that came back fully `clear` — automated checks
catch broken links and invented citations, not tone or meaning-level
mistakes:

1. Scan every claims-ledger flag one more time.
2. Click every link in the issue once.
3. Confirm each note's tone matches the newsletter's practitioner-to-
   practitioner voice — skeptical of hype, concrete over abstract.
4. Approve.

Target 30–45 minutes for this checklist across a full issue. Treat a
session running well past that as a sign the draft itself needs work, not a
reason to skip steps here.

## Step 5 — Render and deploy

Once every entry is `clear` or explicitly approved, let the workflow render
`digest/<iso-week>.md` and `site/index.html` and deploy `site/` to GitHub
Pages. Never allow a partial publish — if any entry is still `blocked` and
unapproved, the workflow should fail loudly rather than ship an issue with
an unresolved citation or an unverifiable vendor/policy claim.

## Step 6 — Manual send (irreducible)

Neither Substack nor Beehiiv exposes a free-tier publish API, so this last
step is always a human action:

1. Paste `digest/<iso-week>.md` into the platform's editor.
2. Confirm the subject line and preview text.
3. Click through every link once more inside the platform's own editor —
   formatting during paste can occasionally break a link even when the
   source markdown was correct.
4. Send.

Budget ~5 minutes for this step. If a free send API ever becomes worth
adopting to remove this last click, see the project playbook's open
decisions on Buttondown as the trade-off (smaller platform, less built-in
discovery, but a working free API).
