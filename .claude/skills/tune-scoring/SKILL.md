---
name: tune-scoring
description: This skill should be used when the user asks to "tune the scoring weights", "review keyword weights", "do the quarterly scoring review", or wants to adjust config/keywords.yml or pipeline/score.py's constants based on real engagement data. A deliberately manual, periodic process, not something to fold into the automated pipeline.
version: 0.1.0
---

# Tune Scoring

Periodically adjust `config/keywords.yml`'s term sets and
`pipeline/score.py`'s scoring constants using real subscriber engagement
data. Per the project playbook §05 and `research-pipeline-spec.md` §10,
§19, and §20, this process is deliberately manual and quarterly — not
automated — because a solo newsletter's early engagement volume is too low
and too noisy to safely auto-tune a relevance filter against. Automating
this risks overfitting the pipeline to a handful of outlier weeks instead of
real signal.

Run this roughly once a quarter, or when the user explicitly asks for a
review. Do not run it more often than that, and do not act on a single
week's data.

## Inputs

- Subscriber engagement data (opens, clicks, replies) per issue for the
  review period, from the newsletter platform's analytics.
- The corresponding `digest/<iso-week>.md` issues and
  `data/ranked/<iso-week>.json` files for those weeks.

## Process

1. Pull click-through and reply data per issue across the review period.
2. Identify the 3–5 highest-engagement and 3–5 lowest-engagement items.
   Look for patterns: which `core_terms`/`context_terms` combinations,
   which `franchise` (weekly/vendor_watch/policy_corner/reader_qa), or which
   source connector they came from.
3. Propose small, specific changes:
   - `config/keywords.yml`: add, remove, or reweight individual terms in
     `core_terms` or `context_terms`.
   - `pipeline/score.py`: adjust a constant such as the `discussion_ratio`
     weighting or the cross-source bonus multiplier (`0.25` in the
     `cluster_score` formula).
   Change one or two things per review, not a wholesale rewrite — the next
   quarter's data needs to be attributable to a specific change, not a pile
   of simultaneous ones.
4. Record the change and the one-line reasoning behind it in the commit
   message or a changelog note. This is the only record of why a given
   quarter's weights look the way they do — don't skip it even for a small
   change.
5. Look for a pattern across the whole quarter before changing anything. A
   single standout week (good or bad) is not sufficient evidence on its own.

## Out of scope for this skill

- Modifying `pipeline/dedup.py`'s clustering thresholds or
  `pipeline/filter.py`'s pass/fail logic structure — these are engineering
  changes to the pipeline's architecture, not weight tuning, and belong in a
  regular development session rather than this recurring review.
- Any change motivated by a single issue's performance rather than a
  quarter-long pattern.
