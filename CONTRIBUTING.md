# Contributing

Guardrail Radar is a solo-maintained, zero-budget project. It's open source
because the discovery pipeline is genuinely useful on its own and being
public is part of how the newsletter is found (see `docs/project-plan.md`
§07) — not because it's actively looking for contributors. That said, a few
kinds of contribution are welcome.

## Bug reports

A source connector breaking is the most likely thing worth reporting — use
the `connector-broken` issue template. Each connector in `connectors/` is
isolated by design (`docs/technical-spec.md` §3), so a fix is usually
scoped to one file.

## Pull requests

Welcome for:

- Fixing a broken connector (an upstream API changed its response shape,
  auth flow, or rate limits).
- Bugs in `pipeline/*.py` (dedup, scoring, filtering, verification,
  rendering).
- Test coverage (`tests/`).

Before opening one:

- Check `docs/technical-spec.md` for the module's intended behavior — the
  spec is the source of truth for how a piece is supposed to work.
- Keep the zero-budget constraint: no new paid APIs, no cloud-provider
  dependency, no heavy ML/data-science libraries (`docs/technical-spec.md`
  §2, §17, §20).
- Add or update the relevant test in `tests/`.

## What's not open to contribution

- Editorial content — the curated notes, Vendor Watch, Policy Corner, and
  what gets included in a given week's issue. Every generative note goes
  through a specific source-grounding and verification process
  (`docs/technical-spec.md` §12–§13, `docs/editorial-guidelines.md`) that
  depends on the maintainer's direct review — this isn't a process that
  scales to outside PRs without weakening the one guarantee the newsletter
  makes to its readers.
- Scoring-weight changes (`config/keywords.yml`, `pipeline/score.py`'s
  constants) — these are tuned quarterly against real engagement data, by
  design (`docs/technical-spec.md` §10, §19). Feel free to open an issue
  suggesting a term or weight worth reconsidering, with the reasoning, for
  the next quarterly review.

## Questions

Open an issue. There's no other support channel for this project.
