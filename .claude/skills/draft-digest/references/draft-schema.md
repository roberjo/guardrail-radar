# `digest/draft/<iso-week>.json` schema

Matches `docs/technical-spec.md` §12.2. The file is a JSON object with three
top-level keys: `subject` (a string, the email platform's subject line),
`intro` (a string, the whole issue's connective narrative), and `items`
(an array — one element per item the issue will include).

```json
{
  "subject": "the literal subject line for Beehiiv — required, distinct from intro",
  "intro": "a short connective narrative for the whole issue — dry wit, still professional; optional, empty string is valid",
  "items": [
    {
      "cluster_id": "must match an id present in data/ranked/<iso-week>.json",
      "title": "string",
      "url": "string",
      "franchise": "weekly | vendor_watch | policy_corner | reader_qa",
      "category": "breaking | new_product | notable | field_notes — the table-of-contents grouping",
      "hook": "one plain-English sentence, front-running the item, on why it's worth a look — the pitch, not the skepticism",
      "note": "the generative \"why this matters\" text — written only from the cluster's stored excerpt",
      "claims": [
        { "text": "a specific claim made in note", "supported_by": "the excerpt phrase that supports it" }
      ],
      "primary_source_url": "required and must resolve when franchise is vendor_watch or policy_corner; omit otherwise"
    }
  ]
}
```

`subject` is added after a design-critique pass found no field anywhere in
the pipeline produced an email subject line, leaving it improvised at send
time, disconnected from drafting/verification. It's the text that goes in
Beehiiv's subject field — required, and distinct from `intro`: give it its
own sentence rather than reusing the intro's opening clause, since it's the
one piece of copy that has to work before anything else gets read. Not
rendered on `site/index.html` (a subject line is an email-only concept);
`pipeline/render.py` surfaces it as a clearly-labeled line at the very top
of `digest/<iso-week>.md`, above the issue's own `# Guardrail Radar — ...`
heading, so the human doing the manual paste-and-send step
(`docs/weekly-runbook.md`) can copy it straight into the platform's subject
field before pasting the rest into the body.

`intro` is added after real user feedback on the first live issue: three
isolated per-item summaries with no frame or synthesis read as a bare link
list, not a newsletter. It's connective tissue, not a factual claim about
any one source — it doesn't get its own claims-ledger entries and
`pipeline/verify.py` doesn't check it — but it still must not invent
specifics that aren't grounded in the items it introduces. `pipeline/
render.py` renders it once, at the top of the issue, in both
`digest/<iso-week>.md` and `site/index.html`.

`hook` is added after real user feedback on the first two live issues:
readers need one plain-English sentence, right up front, on why an item
is worth their time before the longer, more skeptical `note` — what's
actually cool or useful about it, not the compliance-angle caveat. It's
required on every item, not optional like `intro`. Usually it's a tight
paraphrase of the excerpt's own stated pitch (most excerpts already open
with a tagline — "The MCP that proves your AI's integration fixes work,"
"Turn coding with AI into a team sport") rather than something invented
from scratch. Like `intro`, it doesn't get its own claims-ledger
entries — it's a one-line framing of the item, not a specific factual
claim — but it must still be grounded only in the excerpt: no invented
superlatives, stats, or specifics beyond what the excerpt itself states.

A design-critique pass found `hook` was being rendered as a subordinate
line under the item's raw, often jargon-dense source `title` — readers'
best-written copy demoted under scraped metadata. `pipeline/render.py` now
renders `hook` *as the item's headline* (linked to `url`), with the
cleaned `title` demoted to a small secondary caption underneath, in both
`digest/<iso-week>.md` and `site/index.html`. An item with no `hook` still
falls back to `title` as its own headline.

`category` is added after a direct user request for a table of contents,
grouped by area/criticality rather than just a flat list. It's a fixed,
required, four-value enum — distinct from `franchise` (which is about the
newsletter's recurring column format: Vendor Watch, Policy Corner, Reader
Q&A). `pipeline/render.py` builds one table-of-contents block per issue
from it, in a fixed display order, omitting any category with no items
that week:

- `breaking` — urgent and time-sensitive: security incidents,
  compromises, outages, a vendor silently changing behavior. The "you
  need to know this now" bucket.
- `new_product` — a new tool, product, or feature launch worth knowing
  about. Most weeks' most common category.
- `notable` — genuinely impressive, surprising, or eyebrow-raising, but
  not urgent — the "wow" bucket. Use sparingly; if everything is notable,
  nothing is.
- `field_notes` — practitioner commentary, culture, or opinion pieces —
  not a product or a news event, but a real voice worth surfacing.

Like `hook`, `category` is required on every item and doesn't get its own
claims-ledger entry — it's a classification, not a factual claim about
the source — but pick it honestly: a routine product launch dressed up
as `breaking` undermines the one bucket readers should trust to actually
be urgent.

## Worked example

```json
{
  "subject": "Three tools, one theme: nobody trusts the model unsupervised anymore",
  "intro": "Three items this week, and a real theme underneath the sales copy: every one of them puts the AI agent behind a deterministic check it doesn't control — a static analyzer, a keep-it-local architecture, an OT/ICS compliance layer. Nobody's shipping \"trust the model\" anymore, on purpose or not.",
  "items": [
    {
      "cluster_id": "a1b2c3...",
      "title": "Bank X publishes internal Copilot rollout retro",
      "url": "https://example.com/bank-x-copilot-retro",
      "franchise": "weekly",
      "category": "field_notes",
      "hook": "A real bank's own account of what it actually took to get Copilot approved for internal use.",
      "note": "The retro is notable less for the adoption numbers and more for how the team scoped Copilot's suggestions away from any file touching customer PII before rollout — a pattern other regulated teams keep re-deriving from scratch.",
      "claims": [
        {
          "text": "Copilot's suggestions were scoped away from files touching customer PII before rollout",
          "supported_by": "the team excluded any repository path flagged as touching customer PII from Copilot's context window prior to general rollout"
        }
      ]
    },
    {
      "cluster_id": "d4e5f6...",
      "title": "Vendor Y adds SOC 2 Type II report to enterprise tier",
      "url": "https://example.com/vendor-y-blog/soc2",
      "franchise": "vendor_watch",
      "category": "new_product",
      "hook": "One less procurement blocker: Vendor Y's enterprise tier now ships with a SOC 2 Type II report on request.",
      "note": "Vendor Y now offers a SOC 2 Type II report on request for its enterprise tier, closing one of the more common blockers this list hears about from bank security teams evaluating it.",
      "claims": [
        {
          "text": "Vendor Y offers a SOC 2 Type II report on request for its enterprise tier",
          "supported_by": "Enterprise customers can now request our SOC 2 Type II report directly from their account team"
        }
      ],
      "primary_source_url": "https://example.com/vendor-y/changelog/2026-08"
    }
  ]
}
```

Notes on the example:

- The `weekly` entry has no `primary_source_url` — it's not required outside
  `vendor_watch`/`policy_corner`, though it's fine to include one if a good
  primary source exists.
- The `vendor_watch` entry's `primary_source_url` points at the vendor's own
  changelog, not the blog post being commented on — `url` and
  `primary_source_url` can differ; `verify.py` checks both independently.
- Each `claims[].supported_by` string is close enough to actual excerpt
  wording that the fuzzy-match diff in `pipeline/verify.py` will confirm it.
  A `supported_by` value that paraphrases too loosely is exactly what gets
  flagged for the human checklist to re-check by hand.
- `subject` is required, not optional like `intro` — a thin week still
  needs a real subject line. Not checked against any excerpt, but write it
  as its own sentence rather than truncating `intro`'s opening clause.
- `intro` is not checked against any excerpt — it's connective narrative
  for the whole issue, not a per-source claim — but it must still not
  invent specifics that aren't grounded in the items it introduces.
- `hook` is likewise not checked against any excerpt, but is required on
  every item (unlike `intro`) — one plain-English sentence on why the
  item is worth a look, grounded in the excerpt's own pitch.
- `category` (`breaking | new_product | notable | field_notes`) is also
  required on every item — it's the table-of-contents grouping, separate
  from `franchise`. The Bank X entry above is `field_notes` (a rollout
  retro, not a product launch or breaking news); the Vendor Y entry is
  `new_product` (a shipped feature), even though its `franchise` is
  `vendor_watch` — the two fields answer different questions and don't
  have to line up.
