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
status: done
tags: []
updated: '2026-09-20'
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

Written 2026-09-20 on revival. **No specific trigger was named**, so the scope is the substrate
every candidate trigger shares — a deterministic, registry-driven generator that reproduces
GlobalMart's *shape* and scales it — rather than any one trigger's specialisation. Where a trigger
would change the work, it is called out in Out of Scope.

- [x] 1. Given a seed and `--scale 1`, when `globalmart data generate` runs, then every one of the
      215 tables is produced with **exactly** the row count recorded in `data/table-manifest.json`,
      so generated data is directly comparable with the real archive.
- [x] 2. Given the same seed and scale, when the generator runs twice into two directories, then the
      outputs are byte-identical — determinism is the property the whole feature rests on.
- [x] 3. Given two different seeds, when the generator runs, then the outputs differ, so the seed is
      actually doing something.
- [x] 4. Given `--scale N`, when the generator runs, then fact-table row counts scale linearly with N
      and dimension tables scale with `sqrt(N)` (never below their scale-1 count), so a larger
      dataset is wider in facts rather than in reference data.
- [x] 5. Given any generated table, when a column whose name resolves to another table's key is
      inspected, then every value it holds exists in that table's generated key set — referential
      integrity by construction, not by post-hoc repair.
- [x] 6. Given the generated output, when it is loaded with FEAT-005's `data load`, then the load
      succeeds unchanged: same CSV-plus-manifest format, same loader, same DDL, no new code path.
- [x] 7. Given a loaded generated dataset, when the 11 SQL-backed datasets are executed, then all 11
      run — the generated data satisfies the joins the semantic layer actually makes.
- [x] 8. Given a generated dataset, when a `DATE` column is inspected, then its values fall inside
      the same window the real archive covers, so date filters in existing visualizations still
      match rows.
- [x] 9. Given the generator, when it runs, then it **never writes to `data/tables/`** — the
      committed archive is FEAT-005's and is not overwritten by a generated variant. Output goes to
      an explicit directory.
- [x] 10. Given a table added to `data/ddl/globalmart.sql`, when the generator runs, then it is
      generated too, with no edit to the generator — the registry is the source of truth, exactly as
      it is for loading.
- [x] 11. Given a grep of the implementation, when searching for table or column names, then none
      appear: every decision is driven by the DDL and by name *patterns*, never by a hardcoded list.

## Scope

Revived 2026-09-20. Committed scope:
- `src/globalmart/generate.py` — a seeded, deterministic generator for all 215 tables, driven by
  FEAT-005's `TableRegistry` and by column-name patterns, with no table or column hardcoded.
- Referential integrity by construction: a `KeySpace` per table, populated in the registry's
  topological order, so a foreign column can only ever draw from keys that already exist.
- `--scale`, with facts linear and dimensions `sqrt`.
- Output in FEAT-005's exact format (`<dir>/tables/*.csv.gz` plus a `table-manifest.json`), so the
  existing loader consumes it with no new code path.
- `globalmart data generate` plus `--tables-dir` / `--manifest` on `data load`, so a generated
  dataset can be loaded without disturbing the committed archive.

## Out of Scope

- Anything FEAT-005 already delivers: taking custody of the existing archive, the truncate-then-load
  warehouse loader, the `fact_search_event` table, and SQL-dataset validation. This feature does not
  redo that work; it runs alongside FEAT-005's loader, feeding it different bytes.
- **Replacing the committed archive.** `data/tables/` stays exactly as FEAT-005 left it. The
  generator is an alternative source, selected explicitly, never a substitute.
- **Semantic plausibility of values.** Distributions are uniform-ish and unremarkable: a generated
  dataset has the right *shape*, the right keys and the right date windows, not believable retail
  behaviour. Seasonality, realistic price/margin relationships and a deliberately different variant
  shape for generalisation testing are all **trigger-specific specialisations** and are not built,
  because no trigger named them. This is the honest boundary of a substrate built without a driver.
- Regenerating eval ground truth. Any eval with a baked-in expected answer is invalid against
  generated data; that is a consequence to be handled where the evals live, not here.

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

## Outcome (2026-09-20)

Built and proven against a live warehouse. 471 tests, ruff and mypy clean. All 11 acceptance
criteria met.

```
globalmart data generate --out <dir> --seed 5 --scale 1

215 tables, 174,372 rows          identical to the real archive's shape
same seed, twice                  byte-identical
scale 4                           fact_order_line 53,902 -> 215,608 (linear)
                                  dim_currency        10 -> 20      (sqrt)
referential integrity             149 foreign columns, 0 violations, all 215 tables

loaded into gd_demo.globalmart_rebuild:
  all 11 SQL-backed datasets      execute
  fact_order_header -> dim_customer   35,872 of 35,872 join
```

### Revived without a trigger, so the scope is the substrate

The spec said: do not revive this without a specific consumer who can judge plausibility.
None was named. Rather than refuse or invent one, the scope became **what every candidate
trigger shares** — determinism, referential integrity, scale, the real shape — and stopped
where judgement would be required. Plausible distributions, seasonality and a deliberately
different variant shape are all still unbuilt, and the docs say so where someone would
otherwise assume the numbers mean something.

That is also why this came in at `m` rather than the spec's `l`: the specialisations that
made it `l` are the ones deliberately left out.

### A correction to this spec

It said the prior design "exists in this repo's git history on the pre-2026-09-18 FEAT-005
breakdown". **It does not.** The initial commit already carries the post-split version, and
`blake2b`/`KeySpace` appear nowhere in history except in this spec's own text. The design
was never committed. The ideas were good and were adopted on their merits, freshly derived.

### What the live load caught

`hour_start` is an `INTEGER` whose name ends in `_start`. The generator's first version
checked name patterns before the declared type, wrote a date into it, and the warehouse
rejected the load — two tables failed. The DDL's declared type is now authoritative and
names only disambiguate *within* a type. Two tests pin it: one over every column in the DDL,
one asserting that generated values parse as the type the DDL declares.

This is the kind of thing that only a real load finds. The static tests all passed.

### Decisions worth naming

1. **Per-table sub-seeds** (`blake2b(seed, table_name)`) rather than one shared stream. A
   shared stream couples tables: adding one, or changing one table's row count, would shift
   every table generated afterwards and make two runs incomparable for no reason.
2. **Key spaces, not post-hoc repair.** A table mints its keys as it is generated, in the
   registry's load order, and a foreign column draws from the target's minted set. A value
   that was never minted cannot appear, so integrity is structural rather than checked.
3. **Scale 1 reproduces the real row counts exactly**, read from
   `data/table-manifest.json`. The archive is the shape reference, which is what makes a
   generated dataset comparable with the real one instead of merely similar to it.
4. **It refuses to write into `data/`.** The committed archive is FEAT-005's; a variant must
   never silently become it.

### Not done, deliberately

- **Plausibility of values.** Uniform distributions, no seasonality, no price/margin
  relationship. Stated in `docs/data-custody.md` under the generator's own heading, because
  a limit recorded only in a spec is a limit nobody knows about.
- **A second dataset shape** for generalisation testing. That was one of the three candidate
  triggers and it needs the trigger to exist before its shape can be designed.
- **Eval ground truth.** Any eval with a baked-in expected answer is invalid against
  generated data. Handling that belongs where the evals live.
