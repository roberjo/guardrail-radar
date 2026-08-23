# `digest/draft/<iso-week>.json` schema

Matches `docs/technical-spec.md` §12.2. The file is a JSON object with two
top-level keys: `intro` (a string, the whole issue's connective narrative)
and `items` (an array — one element per item the issue will include).

```json
{
  "intro": "a short connective narrative for the whole issue — dry wit, still professional; optional, empty string is valid",
  "items": [
    {
      "cluster_id": "must match an id present in data/ranked/<iso-week>.json",
      "title": "string",
      "url": "string",
      "franchise": "weekly | vendor_watch | policy_corner | reader_qa",
      "note": "the generative \"why this matters\" text — written only from the cluster's stored excerpt",
      "claims": [
        { "text": "a specific claim made in note", "supported_by": "the excerpt phrase that supports it" }
      ],
      "primary_source_url": "required and must resolve when franchise is vendor_watch or policy_corner; omit otherwise"
    }
  ]
}
```

`intro` is added after real user feedback on the first live issue: three
isolated per-item summaries with no frame or synthesis read as a bare link
list, not a newsletter. It's connective tissue, not a factual claim about
any one source — it doesn't get its own claims-ledger entries and
`pipeline/verify.py` doesn't check it — but it still must not invent
specifics that aren't grounded in the items it introduces. `pipeline/
render.py` renders it once, at the top of the issue, in both
`digest/<iso-week>.md` and `site/index.html`.

## Worked example

```json
{
  "intro": "Three items this week, and a real theme underneath the sales copy: every one of them puts the AI agent behind a deterministic check it doesn't control — a static analyzer, a keep-it-local architecture, an OT/ICS compliance layer. Nobody's shipping \"trust the model\" anymore, on purpose or not.",
  "items": [
    {
      "cluster_id": "a1b2c3...",
      "title": "Bank X publishes internal Copilot rollout retro",
      "url": "https://example.com/bank-x-copilot-retro",
      "franchise": "weekly",
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
- `intro` is not checked against any excerpt — it's connective narrative
  for the whole issue, not a per-source claim — but it must still not
  invent specifics that aren't grounded in the items it introduces.
