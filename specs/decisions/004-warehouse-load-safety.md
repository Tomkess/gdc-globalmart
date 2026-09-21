# 004 — Warehouse loads substitute a census and refusal guards for ADR 002's backup

**Status:** Accepted
**Date:** 2026-09-18
**Context:** feat-005 (data generator and warehouse loader); a stated, bounded deviation from ADR 002

## Decision

ADR 002 requires that a destructive remote call be preceded by a backup. For **workspace layouts**
that holds unchanged: a layout is a few megabytes and `backup_workspace()` writes a directly
republishable tree.

For **warehouse data loads** it does not. A load truncates and repopulates 215 tables, roughly 900 MB
at scale 1.0; copying that before every load is impractical and the copy would be no more valuable
than the seed that produced it. So the loader substitutes:

1. **A pre-load census** — row counts plus a per-table checksum of the target schema, recorded in the
   run report before anything is truncated. Forensics: what was there, and did it match what this
   repo believes it generated.
2. **Two refusal guards** — the target profile must declare `data_owned: true`, and the target schema
   must contain only tables the generator's registry knows about. A schema holding anything
   unrecognised is refused, so a load cannot stomp a warehouse this repo does not own.
3. **`--apply` still gates the write**, exactly as ADR 002 requires. Nothing here loosens that.

Stated honestly: the census is **prevention and forensics, not a restore path**. The restore path for
data is regenerating from the recorded seed and scale, which is the reproducibility guarantee
goal-01 is built on. That is acceptable for generated data and would not be acceptable for
hand-authored content — which is why this deviation is scoped to the loader and nothing else.

## Alternatives Considered

| Option | Pros | Cons |
|---|---|---|
| Chosen: census + ownership guards + `--apply`, restore by regeneration | Cheap, fast, catches the realistic accident (wrong schema, unowned warehouse); restore path exists and is exact | Not a true point-in-time restore; a load over irreplaceable rows is unrecoverable, hence the ownership guard |
| Full data backup before every load | Literal ADR 002 compliance; true restore | ~900 MB copied per load; storage and time cost with no benefit over the seed; would discourage running loads at all |
| Warehouse-native snapshot / time travel before load | True restore, cheap where supported | MotherDuck and Postgres differ; couples the repo to warehouse features and makes a third warehouse harder |
| No guard beyond `--apply` | Simplest | A mistyped schema silently destroys a warehouse, and nothing records what was there |

## Consequences

- **Positive:** loads stay fast enough to run routinely; the realistic failure (pointing at the wrong
  schema) is refused rather than survived; the report says what was overwritten.
- **Negative / trade-offs:** this repo cannot restore a warehouse it did not generate, and must not be
  pointed at one — the `data_owned` flag is load-bearing, not decorative.
- **Neutral:** the deviation is bounded to data loads. Layout publishes keep ADR 002's backup in full.

## Revisit Trigger

If a target ever holds rows this repo did not generate — hand-loaded reference data, customer
samples, anything irreplaceable — this deviation stops being safe. At that point either give that
table class a real backup path or move it out of the generated schema entirely.

## Triggered in reverse, 2026-09-21

The trigger fired the other way. `demo-cloud` was `data_owned: false` precisely because the
`globalmart` schema held rows this repo did not generate — the real inherited MotherDuck data, and
the only copy of it after the S3 bucket became unreadable.

**ADR 008 removed that condition.** Every row is now generated from a seed and an explicit window,
so nothing in the schema is irreplaceable and a bad load costs a regeneration rather than the data.
`demo-cloud` is therefore `data_owned: true`.

The guard still matters for its other purpose — a mistyped `--target` must not truncate a warehouse
this repo does not own — and that is unchanged. What has changed for this one profile is the
severity of being wrong about it: it was data loss, it is now downtime. A truncate-then-load leaves
the live workspaces reading an empty schema until it completes, and leaves them empty if it fails
halfway. The mitigation is to run it again, and to not run it while someone is demoing.

If a genuinely safer path is wanted later, load into a staging schema and repoint the datasource,
which the publisher already parameterises.
