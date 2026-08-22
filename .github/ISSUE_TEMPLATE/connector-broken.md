---
name: Connector broken
about: A source API changed or a daily-ingest connector is failing
title: "[connector] "
labels: connector
---

**Which connector** (hn / reddit / github / lobsters / producthunt):

**What's happening** (error message, or "silently returning zero items"):

**Link to the failing workflow run**, if you have one:

**Anything else worth knowing** (e.g. the source's API/docs changed recently):

---
Each connector is isolated by design (docs/technical-spec.md §3) — one
breaking shouldn't take down the others, and a fix is usually scoped to a
single connector file.
