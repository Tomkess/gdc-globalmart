# 007 — The row data is committed, not fetched

**Status:** Accepted
**Date:** 2026-09-18
**Context:** goal-01; FEAT-005. Amends ADR 003 and settles FEAT-005's first open question.

## Decision

GlobalMart's rows are committed to this repository: `data/tables/<table>.csv.gz`, 215 files,
2.3 MB, with `data/table-manifest.json` recording each table's row count, columns and
sha256. There is no archive to host, no download step, and no credential needed to possess
the data. `globalmart data fetch` does not exist; `globalmart data verify` replaces it.

Custody was taken from **MotherDuck `gd_demo.globalmart`**, not from the S3 bucket the spec
named.

## Why

**On committing rather than hosting.** The spec left the archive's home open between a
GitHub release asset, Git LFS, and a bucket under this project's control, to be decided once
the compressed size was known. The size settled it: 174,372 rows across 215 tables compress
to 2.3 MB. All three options were machinery for a problem that does not exist at this scale,
and each reintroduces the thing being fixed — an external location that can rot, lose
access, or drift from what the repo believes. Committing removes the dependency rather than
relocating it.

This amends **ADR 003** ("commit what a human reviews, regenerate what a machine consumes").
Nobody reviews 53,902 order lines. The rule's purpose is to keep the repo's committed surface
meaningful, and the exception earns itself here for a different reason: durability. The
manifest is the reviewable surface; the CSVs are the payload it vouches for.

**On MotherDuck as the source.** The spec planned to pull 214 CSVs from
`s3://gdc-services-aisolutions/local-inference/globalmart/`. That bucket is not readable with
any credentials available here (`InvalidAccessKeyId`), so the risk row reading "the bucket is
lost or access revoked before custody is taken — likelihood Low, impact Critical" had
already materialised. MotherDuck holds the same 214 tables and is what both published orgs
actually query, which makes it the better provenance regardless: it is the data the
workspaces are known to work against, rather than an artifact believed to have produced it.

**On hashing uncompressed bytes.** gzip embeds an mtime, so a digest over the compressed
file changes on every re-compression. Hashing the uncompressed CSV keeps the check
meaningful; `test_recompressing_is_not_a_change` pins it.

**On truncate-then-load rather than upsert.** The DDL declares zero `PRIMARY KEY` and zero
`FOREIGN KEY` across all 215 tables, so there is no merge key to upsert on.
`test_the_ddl_declares_no_constraints` pins that fact, so adding constraints later forces the
strategy to be reconsidered rather than silently invalidated.

## Rejected alternatives

**A hosted archive (release asset / LFS / owned bucket).** Rejected on measurement — see
above. Would be revisited immediately if the dataset grew by two orders of magnitude, which
is what FEAT-007's generator with a `--scale` knob would do.

**Committing plain CSVs instead of gzipped.** 9.4 MB in the working tree against 2.3 MB, for
a diffability nobody will use: a data refresh is a wholesale re-take of custody, not a row
edit. The manifest already shows which tables changed and by how much.

**Loading into `gd_demo.globalmart` to prove the path.** Rejected: that schema is what both
published orgs read. Truncate-then-load would have emptied the live demo data for the
duration, and left it empty had the load failed halfway. A separate `demo-cloud-rebuild`
profile targets `globalmart_rebuild` in the same database, which is what `data_owned`
exists to distinguish.

**Defaulting `data_owned` to true.** Rejected: it would make a mistyped `--target` a
data-loss event. Exactly one profile sets it.

## Consequences

- A clean clone plus warehouse credentials rebuilds the data with no external fetch:
  `uv sync --extra data` then `globalmart data load --target <profile> --apply`.
- `globalmart data verify` runs in CI with no credentials at all, and fails if the committed
  bytes drift from the manifest or if any SQL-backed dataset references a table the DDL does
  not define.
- The warehouse drivers (`duckdb`, `psycopg`) are an optional `data` extra. Capturing,
  splitting and publishing never touch a warehouse, and duckdb alone is a ~15 MB wheel.
- **`fact_search_event` now exists** — 215 tables, not 214. It is the one table whose rows
  are manufactured rather than inherited, is generated from a fixed seed against real
  customer ids and the real date window, and is declared under `synthesised` in the
  manifest. `sql_channel_attribution` has been unable to run since it was written; it runs
  now, verified live.
- Measured on `gd_demo.globalmart_rebuild`: first load 0 → 174,372 rows; second load
  174,372 → 174,372, zero tables changed. The predecessor's second load would have produced
  348,744.
