# 008 — The row data is generated, not committed

**Status:** Accepted
**Date:** 2026-09-20
**Context:** goal-01; FEAT-013. **Supersedes ADR 007**, and in doing so restores ADR 003.

## Decision

GlobalMart's rows leave the repository. `data/tables/*.csv.gz` — 215 files — are deleted from
git and produced on demand by `globalmart.generate` instead.

What stays committed is the **contract**, not the payload:

- `data/ddl/globalmart.sql` — the schema.
- `data/table-manifest.json` — reduced to row counts and columns per table. The `sha256` and
  `bytes` fields go with the files they described.
- The generator itself, which is the only thing that needs to be reviewed.

A generated dataset still writes its own full manifest, with hashes, alongside its output.
That artifact describes one generation run; it is not committed.

**Determinism is redefined, not abandoned.** It was "the committed bytes never change." It
becomes "one seed and one window produce one output." The window is an explicit parameter
recorded in the generated manifest, so any run is reproducible from what it reports — but two
runs on different days deliberately differ, because the window moves with them.

## Why

**Because the data went stale and nobody noticed for 21 months.** The archive spans
2023-01-01 → 2024-12-28. Every dashboard ships a `-11..0` month relative date filter, which
by 2026-09-20 resolved to a window containing no rows at all. Committed data has no mechanism
that keeps it current; generated data can end at today by construction. This is the concrete
failure that forced the decision, and no amount of care with a committed archive prevents its
recurrence — only a process that regenerates does.

**Because the vision already said so.** `specs/VISION.md`: *"schema, **data**, semantic layer
and analytical content — defined as code in the GoodData Python SDK rather than as exported
declarative JSON, so that any domain can be rebuilt from source on demand."* Data defined as
code is what this restores. ADR 007 was the deviation, taken for durability reasons that were
sound at the time.

**Because it restores ADR 003.** That rule — commit what a human reviews, regenerate what a
machine consumes — was explicitly amended by ADR 007 to admit 53,902 order lines nobody
reads. The amendment is withdrawn. The contract is the reviewable surface; the rows are the
machine's business.

**Because two features needed the rows changed at once.** FEAT-011 needs current dates,
FEAT-012 needs `wdf__*` columns. Under ADR 007 each is a 215-file rewrite, reviewed by
eyeballing a diff no one can actually read. Under this decision each is a generator change
plus a rerun.

## What this costs, and why the cost is not accepted

**The data stops being real.** Today's rows were inherited from MotherDuck and carry whatever
retail behaviour the original had. The generator's own docstring is candid: *"no seasonality,
no relationship between price and margin, no realistic basket composition. The distributions
are uniform and unremarkable."*

For evaluation substrate, protocol testing and rebuild verification this would be irrelevant
or even preferable. **GlobalMart is customer-facing**, and a revenue trend that is visibly
uniform noise reads as broken to a prospect however internally valid every number is.

So plausibility is **not** deferred. It becomes part of what generation means here, and
FEAT-013 carries it. This changes the objection FEAT-007 originally raised — that *"inventing
plausible retail data with no consumer able to judge it is how a dataset quietly becomes worse
while every test still passes."* That objection was correct while no consumer existed. One
exists now: a customer demo, where wrong-looking data is immediately and publicly visible.
Plausibility stops being invention and becomes a requirement with a judge.

Scope is bounded by what is *rendered*: the measures the dashboards actually draw must behave
believably over time and against each other. Modelling the whole retail estate to a standard
nobody observes would be the same mistake in the other direction.

**A regenerated dataset is not byte-identical to yesterday's.** Anything that asserted exact
values rather than shape will break, and should — those assertions were coupled to an
accident.

## Rejected alternatives

**Shifting the committed archive forward.** A uniform whole-week date offset would have kept
the real rows and their distributions, preserved every interval and relationship exactly, and
required no ADR at all. Rejected because it treats the symptom: the archive would be current
on the day of the shift and stale again afterwards, and the `wdf__*` columns would still be a
215-file rewrite. It remains the better answer if realism ever outranks currency.

**Hosting the archive** (release asset, LFS, owned bucket). Rejected by ADR 007 on
measurement, and rejected again here for the reason that decision gave: an external location
that can rot, lose access, or drift. Generation has no such location.

**Keeping the archive as a committed fallback.** Rejected: two sources of rows is how they
disagree. If generation is the mechanism, it is the only mechanism.

## Consequences

- `globalmart data verify` can no longer hash committed bytes, because there are none. It
  becomes a check that the contract is coherent and that every SQL-backed dataset resolves
  against the DDL — both of which it already does, and both of which still run offline with
  no credentials.
- A clean clone no longer *possesses* the data. Rebuilding gains a step: generate, then load.
  This is a real regression against ADR 007's "no credential needed to possess the data," and
  is the price of currency.
- The generator needs an explicit window parameter. `generate.date_window()` currently
  *measures* the window by reading the archive it is about to replace, which stops being
  possible and was always circular.
- A scheduled workflow keeps the warehouse current: check whether data is present and recent,
  generate and load when it is not.
- `fact_search_event` stops being a special case. It was the one table already manufactured
  rather than inherited, declared under `synthesised` in the manifest. Now every table is.
- The repository gets substantially smaller, and data changes stop producing diffs that
  cannot be reviewed.
