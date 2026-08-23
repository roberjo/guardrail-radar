---
name: draft-digest
description: This skill should be used when the user asks to "draft this week's digest", "draft the newsletter", "write the why-this-matters notes", "draft the guardrail radar issue", or wants to turn the weekly review packet into digest/draft/<iso-week>.json. Produces source-grounded generative commentary for Guardrail Radar following the project's anti-hallucination rules.
version: 0.1.0
---

# Draft Digest

Turn a week's review packet into source-grounded generative commentary for
Guardrail Radar, the fintech/regulated-industry AI-assisted-development
newsletter. This is the one deliberately non-automated, generative step in
the pipeline (`research-pipeline-spec.md` §12, §20; project playbook §05,
§06) — it stays a human-and-Claude session by design, not a scripted call,
because an ungrounded claim reaching this audience has real consequences.

## Inputs and output

- Input: `digest/review/<iso-week>.md` — the auto-generated, extractive-only
  review packet. Every entry carries a verbatim stored excerpt of the
  original source text.
- Output: `digest/draft/<iso-week>.json` — `{"intro": ..., "items": [...]}`,
  one entry per item the issue will include, in the schema documented in
  `references/draft-schema.md`.

Read the full review packet before drafting anything. An item marked
`[insufficient source text]` in the packet has no usable excerpt — skip it
or flag it explicitly; never invent a note to fill the gap.

## The source-grounding rule

Write every note only from the cluster's stored excerpt text. Do not
introduce a name, number, quote, statistic, or claim that is not present in
that excerpt. If the excerpt does not support a sentence worth writing, omit
the sentence or mark it `"unverified"` rather than write it anyway. The
excerpt is the only ground truth available — the item's title, the
publication's reputation, or general knowledge about the topic are not
substitutes for it.

## Process

1. Read `digest/review/<iso-week>.md` in full.
2. Decide which ~8–10 items to include — editorial judgment, not every
   ranked item needs a note.
3. For each included item, draft a 2–3 sentence practitioner note answering:
   *why does this matter to an engineer adopting AI coding tools under
   compliance, audit, or vendor-risk constraints?* Write in the newsletter's
   practitioner-to-practitioner voice — skeptical of hype, concrete over
   abstract.
3a. Write a one-sentence `hook` for the item, front-running the note —
   plain English, on why it's worth a look at all: what's genuinely
   interesting, useful, or notable about it, before the skepticism kicks
   in. Usually this is a tight paraphrase of the excerpt's own stated
   pitch (most excerpts already open with one — "The MCP that proves your
   AI's integration fixes work," "Turn coding with AI into a team sport")
   rather than something invented from scratch. Required on every item,
   grounded only in the excerpt like the note — no invented superlatives,
   stats, or specifics the excerpt doesn't state.
4. For every factual claim the note makes, add an entry to that item's
   `claims` array pointing at the exact excerpt phrase that supports it.
   This claims ledger is what makes the verification pass (see
   `verify-and-ship-digest`) a scan instead of a re-derivation from scratch —
   do not skip it even for an obvious-seeming claim.
5. Classify the item's `franchise`: `weekly`, `vendor_watch`,
   `policy_corner`, or `reader_qa`.
6. For `vendor_watch` or `policy_corner` items, find and attach a
   `primary_source_url` — the vendor's own changelog/release notes, or the
   official regulatory text/guidance being referenced. This is required, not
   optional, for these two franchises. If no primary source can be found,
   drop the item from this week's draft rather than draft it on a secondary
   or inferred citation.
7. Write a short `intro` — a connective narrative for the whole issue, not
   a per-item summary. Tie the included items together (a shared theme, a
   pattern across sources, why this particular set matters this week) or,
   on a thin week, say so plainly rather than forcing a connection that
   isn't there. Voice: dry wit, still professional — see
   `docs/editorial-guidelines.md`. `intro` is connective tissue, not a
   factual claim about any one source, so it doesn't need its own claims
   ledger entries; it still must not invent specifics (numbers, names,
   quotes) that aren't grounded in the items it's introducing. Optional —
   an empty string is valid on a week where a forced intro would read
   worse than none.
8. Write `{"intro": ..., "items": [...]}` to `digest/draft/<iso-week>.json`.

## Before finishing

Check, don't assume:

- Every `cluster_id` used actually appears in that week's
  `data/ranked/<iso-week>.json`.
- Every `url` and `primary_source_url` is a real link found in the source
  material — never fabricate or guess at a URL.
- Every `vendor_watch`/`policy_corner` entry has `primary_source_url` set.
- Every claim in `claims` has a `supported_by` excerpt phrase that actually
  appears in the item's stored excerpt.
- Every item has a non-empty `hook` — unlike `intro`, this one isn't
  optional.

## Handoff

Drafting a `digest/draft/<iso-week>.json` file does not make an issue ready
to send. The next step is always the `verify-and-ship-digest` skill, which
runs the automated checks and the bounded human checklist before anything
gets published. Do not mark an issue ready or suggest sending directly from
this skill.

## Additional resources

- **`references/draft-schema.md`** — the full `digest/draft/<iso-week>.json`
  schema with a worked example, including a `weekly` entry and a
  `vendor_watch` entry with its primary-source requirement.
