# Guardrail Radar

Signal on AI-assisted software development for engineers working under
regulated/enterprise constraints — fintech, banking, and adjacent
industries where compliance, data governance, and vendor risk shape how AI
coding tools actually get adopted.

Most AI-dev content assumes unrestricted access to third-party LLMs. This
project is for the practitioners who don't have that luxury, and are
solving it in practice.

**Status:** pre-launch. This repo is the open-source discovery-and-curation
pipeline behind the newsletter — see `docs/project-plan.md` for the
audience, business plan, and roadmap.

## How it works

```
daily   → 4 active connectors discover candidates + capture source excerpts
          (a 5th, Reddit, is implemented but deferred — see below)
weekly  → dedup, score, filter → an extractive review packet (automated, no generation)
weekly  → a human, with Claude, drafts source-grounded "why this matters" notes
weekly  → an automated pass verifies every link and citation before anything ships
weekly  → the maintainer runs a short checklist, then pastes the issue and sends it
```

Discovery, scoring, and verification are fully automated. Writing the
commentary and giving final approval stay human-gated on purpose — this is
a compliance-adjacent audience, and a wrong claim costs more than a slower
issue. The full reasoning for what's automated and what isn't is in
`docs/project-plan.md` §05.

## Repository layout

```
connectors/     one module per source (hn, reddit, github, lobsters, producthunt)
pipeline/       dedup, score, filter, excerpt capture, verify, render, notify
config/         keywords.yml (relevance rules), sources.yml (per-source config)
data/           raw/ (per-source daily output) and ranked/ (weekly scored output)
digest/         review/ (packet) → draft/ (drafted notes) → verification/ (checks) → final .md
site/           static digest archive, published via GitHub Pages
tests/          unit tests for pipeline/
docs/           the two planning documents, plus editorial and operational guides
.claude/skills/ structured guidance for the three recurring human steps
```

## Documentation map

- **[`docs/project-plan.md`](docs/project-plan.md)** — audience, business
  plan, marketing/distribution, finance, legal, risk, and roadmap.
- **[`docs/technical-spec.md`](docs/technical-spec.md)** — the full
  engineering build spec: architecture, schema, connectors, scoring,
  verification, and GitHub Actions workflows.
- **[`docs/editorial-guidelines.md`](docs/editorial-guidelines.md)** — voice,
  formats, and the source-grounding rule that keeps AI-assisted commentary
  honest.
- **[`docs/weekly-runbook.md`](docs/weekly-runbook.md)** — the single-page
  "what do I do this week" checklist.
- **[`CHANGELOG.md`](CHANGELOG.md)** — what's changed and when.

## The weekly editorial workflow

Run as three Claude Code skills, one per recurring human step:

1. **`draft-digest`** — turn the week's review packet into source-grounded
   commentary.
2. **`verify-and-ship-digest`** — resolve verification flags, run the
   approval checklist, publish.
3. **`tune-scoring`** — a quarterly, deliberately manual review of keyword
   and scoring weights against real engagement data.

See `docs/weekly-runbook.md` for how these fit together week to week.

## Local development

```bash
pip install -r requirements-dev.txt   # requirements.txt + pytest/ruff/mypy, not installed by production workflows
cp .env.example .env   # fill in connector/notification credentials for local runs
ruff check connectors pipeline tests
mypy connectors pipeline
pytest -q

# hn/lobsters/github need no credentials and can run standalone:
python -m connectors.hn
python -m pipeline.dedup && python -m pipeline.score && python -m pipeline.filter
python -m pipeline.render --target review-packet
```

`connectors/reddit.py` and `connectors/producthunt.py` require credentials
(`.env.example`) — verified by mocked unit tests only, not a live run. See
`CHANGELOG.md` for exactly what's been live-tested versus mock-tested.

**Reddit is currently deferred**, not just uncredentialed: script-app
creation is blocked for this account, and Reddit network-level 403s its
unauthenticated `.json` endpoints from both a dev sandbox and GitHub
Actions runner IPs (confirmed live, not assumed — see `CHANGELOG.md`).
`reddit` is removed from `daily-ingest.yml`'s connector matrix so it isn't
guaranteed-failing on a schedule; the connector and its tests are untouched
and it's a one-line matrix change to re-add once a working credential path
exists.

## Constraints

Zero dollar budget: no cloud provider account, no paid APIs, no paid SaaS
tiers. Everything runs on GitHub's free infrastructure. See
`docs/technical-spec.md` §2 for the full list, and §20 for what's
explicitly out of scope.

## License

[MIT](LICENSE).
