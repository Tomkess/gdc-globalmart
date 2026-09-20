---
abandoned_at: null
abandoned_reason: null
appetite: l
blocked_at: null
blocked_by: null
confidence: medium
created: '2026-09-20'
cycle: null
depends_on:
- feat-005
- feat-007
enables:
- feat-011
- feat-012
goal: goal-01
id: feat-013
name: 'Rows leave the repository: generate GlobalMart data to the current date on demand,
  with the filter columns, driven by a workflow that keeps the warehouse current'
sources: []
status: draft
tags: []
updated: '2026-09-20'
---

## Summary

GlobalMart's 215 CSVs leave git. The rows are produced by the generator instead, always ending
at the current date, and a workflow keeps the warehouse populated without anyone remembering to.

This is ADR 008, which supersedes ADR 007 and restores ADR 003 — commit what a human reviews,
regenerate what a machine consumes. The contract (DDL, row counts, columns) stays committed. The
payload does not.

### What forced it

The committed archive spans **2023-01-01 → 2024-12-28**. Every dashboard ships a `-11..0` month
relative date filter, which on 2026-09-20 resolves to a window with no rows in it. Committed data
has no mechanism that keeps itself current; this went unnoticed for 21 months and was found by
hand, not by any gate.

Two features then needed the rows changed at once — FEAT-011 wants current dates, FEAT-012 wants
`wdf__tenant_id` and `wdf__region` columns. Under ADR 007 each is a 215-file rewrite reviewed by
eyeballing an unreadable diff. Under ADR 008 each is a generator change and a rerun.

### Plausibility is a requirement, not a nicety

GlobalMart is customer-facing and must be bulletproof end to end, so generated data has to *look*
like retail. FEAT-007's generator does not: its own docstring says *"no seasonality, no
relationship between price and margin, no realistic basket composition. The distributions are
uniform and unremarkable."* A flat revenue line reads as broken to a prospect however valid the
numbers are.

FEAT-007 deferred this for a good reason — *"inventing plausible retail data with no consumer able
to judge it is how a dataset quietly becomes worse while every test still passes."* That objection
held while no judge existed. One exists now: a customer demo, where wrong-looking data is
immediately and publicly visible. So plausibility comes into scope here, **bounded by what is
rendered** — the measures the dashboards actually draw must behave believably over time and
against each other. Modelling the rest of the estate to a standard nobody observes is the same
mistake pointing the other way.

This is why the appetite is `l` rather than `m`. Distribution work is the larger half.

### Determinism, redefined

It was "the committed bytes never change." It becomes "one seed and one window produce one
output." The window is an explicit parameter, recorded in the generated manifest, so any run is
reproducible from what it reports — and two runs on different days deliberately differ.

`generate.date_window()` currently *measures* the window by reading the archive it would replace.
That stops being possible, and was always circular.

## Appetite

`l` — 2–6 weeks. The mechanical half (window parameter, filter columns, unpicking the
committed-archive assumptions, the workflow) is 1–2 weeks. The distribution work that makes the
output survive a customer's eye is the rest, and it is the part that cannot be rushed without
producing something that passes every test and still looks wrong.

## Acceptance Criteria

1. `data/tables/*.csv.gz` are deleted from the repository, and nothing reads them.
2. `data/table-manifest.json` is reduced to the contract — row counts and columns per table. The
   `sha256` and `bytes` fields are removed, since they described files that no longer exist.
3. The generator takes an **explicit window**. `date_window()` no longer reads an archive to
   discover one, and generation with no window is an error rather than a fallback to a constant.
4. A generated dataset ends at the run date by default, so the shipped `-11..0` month relative
   filters cover real rows.
5. Generation is reproducible: the same seed and the same explicit window produce byte-identical
   output, and the window actually used is recorded in the generated manifest.
6. The generator emits `wdf__tenant_id` and `wdf__region`, derived coherently from the key graph —
   a fact inherits its store's tenant and region rather than being assigned independently, so no
   row disagrees with the entity it belongs to.
7. Tables with no path to a root entity are either assigned deterministically or listed in an
   explicit allowlist with a stated reason. None are left undecided.
8. The DDL declares the new columns.
9. `globalmart data verify` still runs offline with no credentials, checking that the contract is
   coherent and every SQL-backed dataset resolves against the DDL. It no longer hashes committed
   bytes, because there are none.
10. A workflow determines whether the warehouse holds data that is present and recent enough; when
    it does not, it generates and loads. It is safe to run repeatedly and does not reload
    needlessly.
11. The workflow runs on a schedule and on demand, and reports what it did — including deciding to
    do nothing.
12. FEAT-006's verification passes against freshly generated and loaded data, proving the
    workspaces still work when the rows underneath them are new.
13. **Every measure a dashboard renders behaves believably over time.** Trend, annual seasonality
    and day-of-week effect are present and consistent with each other. A revenue line is not flat
    noise, and a weekend is not indistinguishable from a Tuesday in a retail dataset.
14. **Derived measures agree with their inputs.** Margin follows from price and cost rather than
    being drawn independently; a ratio metric lands in a range a human would accept; counts and
    amounts move together. No dashboard shows two numbers that contradict each other.
15. **Dimensional spread is uneven in the way real estates are.** Stores, regions, products and
    channels differ in size rather than being uniform, so a ranked chart has a shape and a
    top-10 means something.
16. **A human looks at the rendered dashboards and signs off.** No test can decide whether data
    looks right; the acceptance step is opening the real dashboards in a real workspace and
    judging them the way a customer will. This is a required step, not a courtesy.

## Scope

- Deleting the archive and every assumption that it exists: `dataload.verify_data`,
  `generate.date_window`, `base_row_counts`, the CI data gate, and the `--reference-tables` flag.
- The explicit window parameter and its record in the generated manifest.
- `wdf__*` emission from the key graph, reusing `foreign_key_target` / `own_key_column` rather
  than teaching a second module how tables relate.
- DDL updates.
- The workflow: presence-and-freshness check, generate, load, report.
- Distribution modelling for the rendered measures: trend, seasonality, day-of-week, dimensional
  spread, and coherence between derived measures and their inputs.
- A review pass over the actual dashboards, with the findings fed back into the distributions.
- Documentation of the new rebuild path, which gains a step: generate, then load.

## Out of Scope

- **Plausibility beyond what the dashboards render.** Basket-level realism, supplier behaviour
  and cost structures that no visualization draws are out. The bound is what a viewer can see.
- Reshaping or rescaling. `--scale` exists and is untouched.
- The WDF definitions, settings and references — FEAT-012. This supplies the columns only.
- Binding the dashboard date filters — FEAT-011. This makes that fix visible; it does not perform
  it.
- Changing what the workspaces contain. The LDM, metrics and dashboards are unaffected except
  where they assumed specific values.

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Generated data still looks wrong to a customer despite the distribution work | Medium | High | Judge it the way the customer will — render the actual dashboards and look at them. No test suite can answer this, so a human review of the real charts is an acceptance step, not a nicety |
| Distribution work expands without limit — there is always another thing to model | High | Medium | The bound is explicit: what the dashboards render. Anything a visualization does not draw is out of scope by construction |
| FEAT-013 at `l` cannot land before AIS-55's demo | High | High | See Sequencing below — this is a real conflict and needs a deliberate answer, not optimism |
| A clean clone no longer possesses the data — rebuilding now needs warehouse credentials | Certain | Medium | Accepted and documented; it is the direct price of currency, and ADR 008 records it as a regression rather than pretending otherwise |
| Tests or fixtures assert exact values that a regeneration changes | Medium | Medium | Those assertions were coupled to an accident and should break. Convert them to shape assertions as they surface |
| The scheduled workflow reloads needlessly, or truncates a live schema | Medium | High | Freshness check before acting (AC 10); the existing `data_owned` profile guard means exactly one target can be truncated |
| Generation to "today" makes CI non-reproducible run to run | Medium | Medium | Determinism is per seed-and-window (AC 5); CI pins a window rather than using the run date |
| Deleting the archive loses the only copy of the real inherited rows | Low | Medium | It remains in git history, and MotherDuck `gd_demo.globalmart` still holds it. Worth confirming both before the deletion commit, not after |
| `fact_search_event`'s relationship to real customer ids and the real window is lost | Medium | Low | It was already the one synthesised table; now every table is, so the special case simply disappears |

## Sequencing conflict with AIS-55

AIS-55's agreed start is the week of 2026-09-22 and it is customer-facing. This feature is now
`l`. Those do not both fit, and pretending otherwise is how a demo arrives with flat charts.

Three honest options, in the order I would take them:

1. **Demo agent answers, not dashboards.** If the A2A lanes return text plus a small number of
   artifacts, the distribution problem is mostly invisible and FEAT-013's mechanical half is
   enough for the demo. Cheapest, and it narrows what the demo claims.
2. **Keep the real rows for the demo window.** Shift the committed archive forward as an interim
   step, run the demo on data that already looks like retail, and let ADR 008 land properly
   afterwards. This contradicts "no CSV in git" temporarily, which is a cost worth stating out
   loud rather than smuggling.
3. **Do the distribution work first, at speed, for the rendered measures only.** Viable if the
   demo is late enough and the bound is held ruthlessly.

This needs deciding before implementation starts, not during.

## Dependencies

- **Depends on:** feat-007 (the generator, its key graph and its determinism machinery),
  feat-005 (the loader, its census and its `data_owned` guard, both of which survive).
- **Enables:** feat-011 (a window that reaches the present, so bound filters show something) and
  feat-012 (the `wdf__*` columns, without which no workspace data filter can apply).

## Related Research

- Live proof the data filters correctly once a filter binds: `metric_l3_0000_0` on
  `globalmart-ecommerce` returns 960 unfiltered, 262 for 2023 H1, 168 for 2024 H1, and empty for
  2025 H1.
- `generate.date_window()` reads `--reference-tables`, documented as "the real archive, read only
  to measure the date window". `FALLBACK_WINDOW = (2024-01-01, 2026-12-31)` applies only when the
  archive cannot be read.
- The manifest records `bytes`, `columns`, `rows`, `sha256` per table, with top-level `source`,
  `synthesised`, `version`. Generated output writes `source.kind = "generated"` with seed and
  scale.
- `dim_store` holds 20 stores across four regions (`NORTH`, `SOUTH`, `EAST`, `WEST`), which is why
  the region layer can use real values rather than invented ones.
- Column reach across the 215 tables: `customer_id` 40, `store_id` 39, `product_id` 32. Nothing
  exceeds 40, so the tenant axis must be a synthetic column — confirmed by `demo_ecommerce` in the
  same org, which uses a synthetic `wdf__client_id`.
- `fact_aged_inventory` and `fact_purchase_order_line` carry no date column at all.

## Open Questions

- **Does AIS-55 demo these dashboards?** If yes, uniform distributions become a blocker rather
  than an accepted cost, and that changes this feature's shape. Worth answering before starting.
- What counts as "recent enough" for the freshness check — the window ends within a month, within
  a quarter? Too tight and the workflow churns; too loose and staleness creeps back.
- Should the scheduled run load into the live `gd_demo.globalmart` schema that both published orgs
  read, or only into `globalmart_rebuild`? The former keeps demos current and is also how a
  scheduled job empties a live demo if it fails halfway.
- Does anything outside this repo consume `data/tables/` — an eval harness, a notebook, a script
  in Misc? Deleting it is cheap to do and expensive to discover the consumers of afterwards.
- Should the contract manifest keep `synthesised`, now that the answer is "all of them"?
