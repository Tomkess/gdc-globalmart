---
abandoned_at: null
abandoned_reason: null
appetite: l
blocked_at: null
blocked_by: null
confidence: low
created: '2026-09-18'
cycle: null
depends_on: []
enables: []
goal: goal-01
id: feat-007
name: 'Synthetic GlobalMart data generator: seeded, deterministic, scale-parameterised
  replacement for the inherited CSV archive, enabling reshaped and resized datasets'
sources: []
status: draft
tags: []
updated: '2026-09-18'
---

## Summary

FEAT-005 takes custody of GlobalMart's existing 214 CSVs — fetches them once, pins them in a
committed archive manifest, loads them idempotently — which solves goal-01's actual problem
(unowned, unrebuildable bytes) without touching the data itself. This feature is the road not
taken: replace those inherited rows with a seeded generator that can produce GlobalMart at any
scale or shape. It is parked, not cancelled — real, bounded needs would justify it, but none exist
today, and building it now would mean inventing retail data whose plausibility and referential
integrity are hard to get right, to solve a problem FEAT-005 already closed more cheaply.

## Appetite

`l` — 2–6 weeks

## Acceptance Criteria

None yet — this is a parked idea, not a committed scope. If picked up, `/breakdown` should derive
criteria from the "What this feature would add" list below rather than from FEAT-005's superseded
generator design, since the trigger that revives this feature determines which of those additions
actually matters.

## Scope

Undetermined until revived. Candidate scope, not yet committed:
- A seeded, deterministic generator for some or all of GlobalMart's 215 tables.
- A `--scale` parameter for producing larger or smaller datasets from the same seed.
- Support for a second, deliberately different dataset shape (variant category mix, seasonality)
  for testing whether an agent generalises rather than memorises.

## Out of Scope

- Anything FEAT-005 already delivers: taking custody of the existing archive, the truncate-then-load
  warehouse loader, the `fact_search_event` table, and SQL-dataset validation. This feature does not
  redo that work; it would run alongside FEAT-005's loader, feeding it different bytes.
- Regenerating GlobalMart's *current* shape and values — that is exactly what FEAT-005 preserves.

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Generated retail data is subtly implausible (broken seasonality, degenerate distributions), and evals silently measure a worse dataset without anyone noticing | High | High | This is the core reason the feature is parked rather than built speculatively — do not revive it without a specific consumer who can judge plausibility against a real need |
| Referential integrity across 215 tables with zero declared primary keys in the DDL is easy to get subtly wrong | Medium | High | Reuse the topological `TableRegistry` FEAT-005 builds from the DDL rather than re-deriving dependency order |
| Regenerating invalidates every eval test case with a baked-in expected answer, exactly as it would have under the original FEAT-005 design | High | Medium | Pair any revival with regenerating the eval ground truth in the same body of work, never as an afterthought |
| The feature stays parked indefinitely and the design notes rot | Low | Low | The prior design (blake2b sub-seeds, KeySpace-based integrity, sqlglot validation, scale-linear facts) is preserved in this repo's git history on the pre-2026-09-18 FEAT-005 breakdown; point there rather than re-deriving from memory |

## Dependencies

- **Depends on:** feat-005 (its `TableRegistry`, DDL parsing and warehouse loaders are the
  substrate this would generate into; this feature would not duplicate them).
- **Enables:** nothing currently. A future eval-scale or generalisation-testing need would be the
  actual driver.

## Related Research

- Split out of FEAT-005 on 2026-09-18 (see that feature's spec, "Out of Scope", and ADR 003's
  2026-09-18 amendment) once the real problem was identified as bucket ownership, not data
  authenticity.
- Prior full design (per-table `blake2b` sub-seeds, `KeySpace`-based referential integrity built in
  topological order, `sqlglot` static validation of the 11 SQL datasets, scale-linear facts with
  `sqrt(scale)` dimensions) exists in this repo's git history on the pre-2026-09-18 version of
  FEAT-005's `breakdown.md` — read that commit before designing from scratch if this is revived.

## Open Questions

- What concrete, real need would trigger picking this up — a specific load-testing requirement, a
  generalisation-testing requirement, or the archive host actually failing? Until one exists, this
  stays an idea rather than a draft with committed acceptance criteria.
- If revived, does it replace FEAT-005's archive entirely, or run alongside it as an alternate data
  source selected per target profile (so evals could compare "against the real archive" vs "against
  a generated variant")?
- **Confidence is low on this `l`-appetite feature; before committing to it, consider an `xs` spike:**
  `meridian new "spike: what concrete need would justify a synthetic GlobalMart generator" --appetite xs`
  A spike here should produce a decision — build it, or leave it parked — not shippable code.
