# Guardrail Radar — Full Project Plan

**Repo:** `guardrail-radar` | **Newsletter brand:** Guardrail Radar
**Owner:** John | **Budget:** $0 | **Status:** Pre-launch

---

## 1. Executive Summary

Guardrail Radar is a niche newsletter (and companion open-source signal-discovery pipeline) covering AI-assisted software development for engineers working under regulated/enterprise constraints — fintech, banking, and adjacent industries where compliance, data governance, and vendor risk shape how AI coding tools can actually be adopted.

The wedge is narrow on purpose: most AI-dev content assumes unrestricted access to third-party LLMs. Guardrail Radar speaks to the practitioners who don't have that luxury and are solving it in practice — the audience you're already part of.

---

## 2. Target Audience & Demographics

### Primary audience
- **Software engineers and tech leads at banks, fintechs, insurers, and other regulated enterprises** who are personally trying to adopt AI coding assistants (Copilot, Claude Code, Cursor) within compliance constraints.
- Mid-to-senior IC or lead level — enough seniority to influence tooling decisions, not so senior they've delegated hands-on work entirely.
- Likely also active in internal platform/DevEx or architecture roles, since they're the ones building the guardrails (secrets scanning, PR bots, approved-model gateways).

### Secondary audience
- Engineering managers/directors evaluating AI tooling rollout and needing to justify it to compliance/risk.
- Compliance/risk/security professionals who need to understand what engineers actually want to do, to write sane policy instead of blanket bans.
- AI dev-tool vendors selling into regulated industries, looking for market signal (smaller, more transactional segment — don't design content for them, but don't turn them away as subscribers).

### Explicitly not the primary target
- General AI-news consumers (saturated space: TLDR AI, Ben's Bites, The Neuron).
- Consumer fintech / personal finance readers — this is an engineering practitioner newsletter, not a fintech-industry newsletter.

### Realistic scale expectations (bootstrap, zero-budget, solo)
- Weeks 1–4: 0–50 subscribers (personal network, LinkedIn, initial posts)
- Months 2–3: 50–300 (organic sharing, HN/Reddit engagement, guardrail-radar repo as a discovery surface)
- Month 6 target: 500–1,000 highly engaged subscribers — small in absolute terms, but this audience has outsized word-of-mouth value because sharing it inside a bank's internal channels carries professional credibility.

---

## 3. Business Plan

### Phase 1 — Bootstrap (Months 0–2)
- Goal: validate the content/audience fit, not revenue.
- Publish weekly, manually curated from the guardrail-radar pipeline output.
- No monetization yet. Focus entirely on consistency and quality of curation.

### Phase 2 — Growth (Months 3–6)
- Goal: grow to a few hundred engaged subscribers via organic/content-led channels only (see Marketing section).
- Introduce a light "About / Sponsor" page — no active sponsor outreach yet, just make it possible for inbound interest.
- Start tracking which curated stories get the most clicks/replies to tune the pipeline's scoring weights.

### Phase 3 — Sustainability (Month 6+)
- Only if subscriber count and engagement justify it: light sponsorship (a single "supported by" line, not display ads) from developer-tool or compliance-tooling vendors relevant to the audience.
- Evaluate a paid tier (deeper analysis, guardrail pattern deep-dives) only once free-tier platform limits are actually being hit — not before.
- This is a directional plan, not a revenue commitment — the project's real success metric in Phase 1–2 is engaged readership, not income. I'm not a financial advisor; any actual sponsorship/paid-tier terms should be evaluated on their own merits when the opportunity is real.

### Success metrics (in priority order)
1. Reply/forward rate (signals real practitioner engagement — this is the audience's core value)
2. Open rate (platform-reported, free tier)
3. Subscriber growth rate (secondary to the above — vanity metric if the first two are weak)
4. guardrail-radar repo stars/traffic (proxy for the content pipeline's own credibility as a public artifact)

---

## 4. Engineering

### 4.1 Components
| Component | Role |
|---|---|
| `guardrail-radar` repo (research pipeline) | Automated discovery/scoring of candidate content — see prior technical spec |
| Curation step | Manual — you review the top-ranked weekly items and select ~5–8 for the issue |
| Drafting | AI-assisted first draft (Claude) from curated links/notes, edited by you for voice |
| Publishing platform | Free-tier Substack or Beehiiv (see Hosting) |
| Public digest site | GitHub Pages, generated from the same pipeline (see technical spec, Section 11) |

### 4.2 Build reference
The connector/scoring/dedup architecture, repo structure, data schema, GitHub Actions workflows, and required secrets are fully specified in the separate document: `research-pipeline-spec.md` (already delivered). This project plan doesn't repeat that detail — treat the two documents as companions.

### 4.3 Engineering effort budget
- Initial build (Phase 1 connectors + workflows): estimate 15–25 hours, doable in evenings/weekends given your existing AWS/Python/Terraform-adjacent skill set transferring directly to GitHub Actions + Python.
- Ongoing maintenance: 1–2 hours/week (tuning keyword weights, fixing connector breakage when a source API changes).

---

## 5. Marketing & Distribution

All channels below are free/organic — no paid acquisition, consistent with the zero-budget constraint.

### 5.1 Primary channels
- **LinkedIn** — your existing professional network (Principal/Staff SWE track credibility lends authenticity). Post issue highlights, not just links — a short take on why a curated item matters to regulated-industry engineers.
- **guardrail-radar public repo + GitHub Pages digest** — a self-promoting artifact. Developers who find the repo (via GitHub search, HN, word of mouth) discover the newsletter as a natural next step. This mirrors the pattern you've already used with roomba-telemetry.
- **Hacker News / relevant subreddits** — participate genuinely in threads about AI-dev tooling in regulated contexts; mention the newsletter only where it's actually relevant, not as drive-by promotion (this audience penalizes spam hard).

### 5.2 Secondary channels
- Internal-facing: if your employer's outside-activity policy permits, mentioning the project (without proprietary detail) in professional circles/meetups.
- Fintech/dev Slack and Discord communities where AI-tooling adoption is actively discussed.

### 5.3 Content-led SEO
- The GitHub Pages digest site accumulates weekly indexed content over time — plain HTML, descriptive titles, and permalinks per week are enough at this scale; no paid SEO tooling needed.

---

## 6. Accounting & Finance

### 6.1 Cost structure — target $0
| Item | Cost | Notes |
|---|---|---|
| Newsletter platform (Substack/Beehiiv free tier) | $0 | Free tier limits are generous at <1,000 subscribers |
| GitHub (public repo + Actions + Pages) | $0 | Public repos get free unlimited Actions minutes |
| Domain name | $0 initially | Defer — use platform subdomain until there's real traction |
| Internal "review packet ready" notification | $0 | A GitHub Issue, opened with the built-in `GITHUB_TOKEN` — no email service, no app password to configure |

### 6.2 Trigger thresholds (when to reconsider $0)
- Custom domain (~$12/year): once subscriber count or brand identity justifies moving off a subdomain.
- Paid newsletter tier: only if subscriber count exceeds the free tier's subscriber cap (varies by platform — check current limits before that point).
- These are the only two costs likely to ever apply, and both are optional, low, and deferred.

### 6.3 Tracking
- A single spreadsheet (subscriber count, open/reply rate, time spent per week) is sufficient — no accounting software needed at this scale, since there's no revenue or expense flow yet to reconcile.

---

## 7. Hosting

| Surface | Host | Cost |
|---|---|---|
| Newsletter (email + landing page) | Substack or Beehiiv free tier | $0 |
| Research pipeline compute | GitHub Actions (scheduled workflows) | $0 |
| Pipeline data store | Git-committed JSON in the repo | $0 |
| Public weekly digest site | GitHub Pages | $0 |

No cloud provider account of any kind — consistent with your instruction to avoid AWS/GCP/Azure entirely for this project.

---

## 8. Legal & Compliance Considerations

Worth flagging explicitly given your employer is a regulated bank — I'm not a lawyer, so treat this as pointers to check, not legal advice:

- **Outside-activity / moonlighting policy**: many regulated-industry employers require disclosure (or even approval) of side projects, especially ones adjacent to your day-job domain (AI tooling, engineering practices). Worth confirming your employer's policy before public launch.
- **IP assignment clauses**: some employment agreements assign IP for anything created using company time/equipment, or sometimes anything in a related field regardless of equipment — worth checking your own agreement's scope before building on company hardware/time.
- **No proprietary content**: keep the newsletter and pipeline entirely free of specifics about your employer's internal systems, architecture, or tooling (e.g., don't reference TF Guardian, portal-platform, or other internal-project specifics by name or detail) — curate and comment on public/industry content only.
- **Separate accounts/resources**: use personal GitHub, email, and dev environment for this project, not employer-provisioned accounts or work time, to keep a clean separation.

---

## 9. Risk Assessment

| Risk | Mitigation |
|---|---|
| Source APIs change/break (Reddit, GitHub, etc.) | Each connector is isolated (Section 3, technical spec) — one breaking doesn't take down the pipeline |
| Niche audience caps growth | Accepted trade-off — niche is the point; success is measured by engagement, not raw subscriber count |
| Solo-maintainer burnout | Keep weekly cadence sustainable (curation, not full research, is the manual step); pipeline automates the time-consuming discovery work |
| Employer conflict-of-interest | Address proactively per Section 8, before public launch, not after |
| Low initial engagement | Phase 1 explicitly treats the first 2 months as validation, not growth — expectations are calibrated accordingly |

---

## 10. Roadmap (First 12 Weeks)

| Weeks | Milestone |
|---|---|
| 1–2 | Build guardrail-radar Phase 1 pipeline (HN + Reddit + GitHub connectors, dedup/scoring, manual review) |
| 3 | Set up newsletter platform, landing page, GitHub Pages digest site; confirm employer outside-activity policy |
| 4 | First issue — manually curated from pipeline output, sent to personal network |
| 5–8 | Weekly cadence; add lobste.rs + Product Hunt connectors; begin LinkedIn/organic promotion |
| 9–12 | Review engagement data, tune scoring/keyword weights, evaluate whether Phase 2 growth tactics are working; revisit this plan with real data |

---

## 11. Open Decisions

- Final newsletter brand name (Guardrail Radar assumed here — confirm or revise).
- Substack vs. Beehiiv (both free-tier viable — worth a quick hands-on comparison before committing).
- Publishing cadence (weekly assumed — could start biweekly if curation time is tight in Phase 1).
