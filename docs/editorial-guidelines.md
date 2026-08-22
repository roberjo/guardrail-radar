# Editorial guidelines

The voice, format, and integrity rules for anything Guardrail Radar
publishes. This is the reference a human collaborator (including a future
version of the maintainer) should be able to read on its own, without
opening the full project plan or technical spec. The underlying rationale
lives in `docs/project-plan.md` §05–§06 and is enforced mechanically by
`docs/technical-spec.md` §12–§13; this page is the practitioner-facing
summary of both.

## Who this is for

Primary: mid-to-senior engineers and tech leads at banks, fintechs, and
insurers adopting Copilot/Claude Code/Cursor within compliance constraints.
Secondary: engineering managers and compliance/risk professionals who need
to understand what engineers actually want, in order to write sane policy.
Not the target: general AI-news readers — that space is already saturated.

Write like you're talking to a peer who's solving the same problem you are,
not explaining AI to someone who's never touched it, and not selling
anything to a prospect.

## Voice

- Practitioner-to-practitioner. Skeptical of hype, concrete over abstract.
- Specific beats clever. Name the actual constraint (an audit requirement,
  a vendor's data-residency clause) instead of gesturing at "compliance
  concerns" in the abstract.
- No apologies, no hedging filler ("it's worth noting that…"). If a claim
  is uncertain, say so plainly and say why.

## The two-layer content model

Every issue has two kinds of content, and they're held to different
standards because only one of them is generated:

1. **Extractive** — title, link, score, and a verbatim excerpt of the
   source. Produced entirely by the pipeline. No generation happens here,
   so there's nothing to hallucinate, and nothing here needs review.
2. **Generative** — the "why this matters" note, and the Vendor Watch /
   Policy Corner franchises. Written by the maintainer with Claude's
   assistance, grounded only in the stored excerpt, and never sent without
   passing verification (`docs/technical-spec.md` §13) and the bounded
   human checklist. See the **`draft-digest`** and **`verify-and-ship-digest`**
   skills for the mechanical process.

## Formats

- **Weekly note** — 2–3 sentences per item, every issue. Answers: why does
  this matter to an engineer working under compliance/audit/vendor-risk
  constraints?
- **Vendor Watch** (monthly) — which AI-coding vendors shipped audit-log,
  SOC2, on-prem, or data-residency features. Every claim requires a primary
  source (the vendor's own changelog/release notes) — not the blog post
  covering it.
- **Policy Corner** (as regulatory news actually touches developer tooling)
  — plain-English translation of the official text or guidance, not
  secondhand commentary on it. Same primary-source rule as Vendor Watch.
- **Reader Q&A** (occasional) — one real subscriber question, answered
  publicly. Cheap to produce, and a strong reply-rate signal.

## The one rule that matters most

Write every generative note only from the item's stored source excerpt.
Never introduce a name, number, quote, or claim that isn't present in that
excerpt — not from the title, not from general knowledge of the topic, not
from what a similar story usually says. If the excerpt doesn't support a
sentence worth writing, omit it or mark it unverified instead of writing it
anyway.

This is a permanent rule, not a launch-phase safeguard to relax once the
newsletter has a track record. The audience makes real compliance decisions
off what they read here — see `docs/technical-spec.md` §2's non-goals and
`docs/project-plan.md`'s risk assessment.

## Success metrics, in priority order

1. Reply/forward rate — the real signal that a note landed.
2. Open rate.
3. Subscriber growth — secondary; a vanity number if the above two are weak.
4. Repo stars/traffic — a proxy for the pipeline's own credibility as a
   public artifact.

Reply and forward rate outrank subscriber growth on purpose: a smaller,
correctly-served list is worth more to this audience — and to eventual
sponsors — than a larger, thinner one.
