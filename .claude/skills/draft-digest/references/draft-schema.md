# `digest/draft/<iso-week>.json` schema

Matches `research-pipeline-spec.md` §12.2. The file is a JSON array; each
element is one item the issue will include.

```json
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
```

## Worked example

```json
[
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
