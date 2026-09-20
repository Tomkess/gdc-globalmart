---
abandoned_at: null
abandoned_reason: null
appetite: m
blocked_at: null
blocked_by: null
confidence: high
created: '2026-09-18'
cycle: null
depends_on:
- feat-001
enables:
- feat-006
goal: goal-01
id: feat-005
name: Own the GlobalMart data artifact and load it idempotently into MotherDuck or
  Postgres, replacing the unowned S3 bucket
sources: []
status: done
tags: []
updated: '2026-09-20'
---

## Summary

GlobalMart's row data exists nowhere in any repo. It is 214 pre-made CSVs sitting in
`s3://gdc-services-aisolutions/local-inference/globalmart/`, a bucket this project does not own,
produced by a generator that was never committed. The predecessor's loader walked a hardcoded
214-entry `LOAD_ORDER` running
`INSERT INTO {schema}.{table} SELECT * FROM read_csv_auto('s3://.../{table}.csv', header=true)`.
Delete the bucket and GlobalMart is unrecoverable; re-run the loader and every table silently
doubles. Both violate goal-01, which requires that a clean clone plus credentials rebuilds
everything with no manual step.

The problem is *ownership and idempotency*, not authenticity. The data does not need to be
different — it needs to be ours, durable, and loadable twice without doubling. So this feature takes
custody of the bytes: pull the CSVs down once, verify and checksum them, publish them as a versioned
archive in a location under this project's control, commit the manifest that pins exactly which
archive is correct, and load from there. It also fixes the two defects that make the current data
unusable for a cold rebuild — the missing `fact_search_event` table and the doubling load.

Regenerating the data from scratch — a synthetic generator with a seed and a scale knob — is a
separate, much larger question, parked as FEAT-007. It buys the ability to *reshape* the dataset,
which nothing currently needs. This feature buys reproducibility, which everything needs, at a small
fraction of the cost.

## Appetite

`m` — 1–2 weeks

## Acceptance Criteria

- [x] 1. Given a clean clone, credentials for the archive location and an empty warehouse, when
      `globalmart data fetch` then `globalmart data load --target <profile> --apply` are run, then
      all 215 tables exist and are populated, with no access to
      `s3://gdc-services-aisolutions/` required at any point.
- [x] 2. Given the committed `data/archive-manifest.json`, when `globalmart data fetch` runs, then
      the downloaded archive's sha256 matches the pinned digest and every per-table row count and
      checksum matches; a mismatch fails the command naming the offending table, so silent drift
      between the archive and what the repo believes is impossible.
- [x] 3. Given `globalmart data load --target <profile> --apply` run twice against the same schema,
      when the second run completes, then every table's row count is identical to after the first —
      truncate-then-load, never append. (The predecessor's plain `INSERT` doubled every table.)
- [x] 4. Given the dataset `sql_channel_attribution`, which selects `FROM {schema}.fact_search_event`,
      when a cold rebuild completes, then that table exists and is populated, and the dataset
      resolves. (No DDL and no CSV exists for it today; tracked and never closed in the predecessor
      repo.)
- [x] 5. Given all 11 SQL-backed datasets in the parent layout, when validation runs after a load,
      then each statement parses and executes against the loaded schema, and any column it references
      that the DDL does not define fails the command naming the dataset and the column.
- [x] 6. Given a target profile without `data_owned: true`, when a load is attempted, then it is
      refused before any truncate, naming the profile — this repo never truncates a warehouse it has
      not been told it owns (ADR 004).
- [x] 7. Given a target schema containing a table the registry does not know, when a load is
      attempted, then it is refused and the unknown table is named, so a mistyped schema cannot
      destroy an unrelated warehouse.
- [x] 8. Given a load about to run, when it starts, then a pre-load census of row counts per table is
      recorded in the run report before any truncate, so what was overwritten is known afterwards.
- [x] 9. Given the load order, when a warehouse with foreign-key enforcement is targeted, then tables
      are truncated in reverse dependency order and loaded in dependency order, so no load fails on a
      constraint.
- [ ] 10. **NOT MET.** Given both a MotherDuck and a Postgres profile, when each is loaded, then both
      succeed against the same archive and the same DDL, with only the adapter differing.
      *(`loaders/postgres.py` is written and wired, but no Postgres target exists to run it
      against — the `local-inference` profile is still commented out. MotherDuck is proven;
      Postgres is not.)*
- [x] 11. Given a grep of the implementation, when searching for bucket names, hosts, schemas or
      warehouse identifiers, then none appear outside `config/targets.yaml` and
      `data/archive-manifest.json`.

## Scope

- A one-time custody transfer: fetch the 214 CSVs from the current bucket, verify them, compress
  them into a single versioned archive, and publish it to a location this project controls.
- `data/archive-manifest.json` — committed. Pins the archive version, its URL, its sha256, and per
  table the row count and checksum. This file is the contract; the archive is just bytes.
- `globalmart data fetch` — downloads and verifies the archive into a gitignored local cache,
  idempotent and resumable, skipping the download when the cached copy already matches the digest.
- `globalmart data load --target <profile>` — applies the DDL, then truncate-then-load in
  dependency-safe order. Rehearsal by default, writes under `--apply` (ADR 002 / ADR 004).
- The table registry derived from `data/ddl/globalmart.sql`, replacing the predecessor's hardcoded
  `LOAD_ORDER`, including the dependency graph used for ordering.
- `fact_search_event`: DDL plus rows, so `sql_channel_attribution` resolves on a cold rebuild.
- Warehouse adapters for MotherDuck and Postgres, extending FEAT-002's `datasource.py` pattern.
- Validation that all 11 SQL-backed datasets execute against the loaded schema.
- The ADR 004 safety set: `data_owned` guard, registry-subset check, pre-load census.

## Out of Scope

- **Synthetic data generation** — a seeded generator, a `--scale` knob, reshaping or resizing the
  dataset. Parked as FEAT-007; this feature deliberately preserves the existing rows exactly.
- Changing the data's content, distributions or date range. What is in the archive is what loads. (It
  follows that the date-anchor question that applied to a generator does not arise here.)
- Regenerating the eval test cases. The rows are unchanged, so existing expected answers stay valid —
  this is the practical upside of preserving rather than regenerating.
- Adding an LDM dataset for `fact_search_event` in the parent (it would make 226). The physical table
  is created so the existing SQL dataset resolves; exposing it as its own dataset is an LDM change
  belonging with FEAT-001's tree.
- Warehouses beyond MotherDuck and Postgres.

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The archive location becomes the new single point of failure — the same problem, relocated | Medium | High | It is owned by this project, its digest is committed, and the local cache plus any prior clone is a viable copy. Ownership, not redundancy, is what was missing before |
| The bucket is lost or access revoked before custody is taken | Low | Critical | This is the first task in the feature and should be done immediately, ahead of any other work here — everything else is recoverable, the bytes are not |
| Archive is too large for the chosen host (release asset limits, LFS quota) | Medium | Medium | Measure compressed size in task 1 before choosing the host; a bucket this project owns is the fallback and needs no size negotiation |
| `fact_search_event`'s shape must be inferred from a SQL statement rather than from a DDL | High | Medium | Derive the column set from `sql_channel_attribution`'s statement, generate plausible rows consistent with the existing fact tables' keys, and document that this one table is synthesised rather than inherited |
| Truncate-then-load is destructive and the restore path is a re-fetch, not a backup | Medium | Medium | ADR 004's guards: `data_owned`, registry-subset refusal, pre-load census, `--apply`. The archive makes re-fetch a genuine restore path, which the generator-based plan could not offer |
| CSVs carry embedded type or encoding quirks that only surface on Postgres | Medium | Medium | Load both warehouses in CI-like fashion during the feature, not after; AC #10 exists for this |

## Dependencies

- **Depends on:** feat-001 (`config.py`, `TargetProfile`, `layout_io.read_tree` for SQL-dataset
  validation), feat-002 (`datasource.py` adapter pattern, `traversal.iter_sql_statements`, the
  `--apply` gate).
- **Enables:** feat-006 (nothing computes without rows).
- **External:** read access to `s3://gdc-services-aisolutions/local-inference/globalmart/` **once**,
  for the custody transfer; thereafter none.

## Related Research

- The predecessor's `loaders/motherduck.py` used plain `INSERT ... SELECT * FROM read_csv_auto(...)`
  with no truncate, so a second load doubled every table. Its `LOAD_ORDER` list is a useful
  dependency ordering to cross-check the DDL-derived registry against.
- `data/ddl/globalmart.sql` is schema-only, 214 `CREATE TABLE` statements under a `{schema_name}`
  placeholder, zero rows, and zero `PRIMARY KEY` declarations — which is why the load is
  truncate-then-load rather than upsert: there is no merge key.
- `sql_channel_attribution` selects `FROM globalmart.fact_search_event`, a table with no DDL and no
  CSV. Open and unclosed in the predecessor repo.
- ADR 004 records why warehouse loads substitute a census and ownership guards for ADR 002's backup.
- ADR 003's rule — commit what a human reviews, regenerate what a machine consumes — is amended by
  this feature: the data is now *fetched and verified* rather than regenerated, so the committed
  artefact is the manifest rather than a generator plus seed.

## Open Questions

- Where the archive lives: a GitHub release asset on `Tomkess/gdc-globalmart`, Git LFS, or an S3
  bucket under this project's control. Decide in task 1, once the compressed size is known — under a
  gigabyte makes a release asset the simplest thing that works.
- Whether `fact_search_event`'s synthesised rows should be committed as a small CSV in the repo
  (it is one table, likely small) rather than folded into the archive. Committing it keeps the one
  hand-made piece of data reviewable.
- Whether `globalmart data fetch` should run automatically as part of `load` when the cache is cold,
  or stay an explicit separate step. Explicit is safer for a command that reaches the network;
  convenience argues the other way.

## Outcome (2026-09-18)

Built and loaded. 304 tests, ruff and mypy clean, `data verify` wired into CI.

```
                          committed        loaded into gd_demo.globalmart_rebuild
tables                    215              215
rows                      174,372          174,372
size                      2.3 MB gzipped
first  load               —                0 -> 174,372   (215 tables changed)
second load               —                174,372 -> 174,372   (0 tables changed)
SQL datasets executed     —                11 / 11
```

That second load is the predecessor's defect, absent. Its plain `INSERT` would have
produced 348,744.

### The two biggest decisions were settled by measurement, not by the plan

1. **The archive does not exist, because the data is committed.** The spec left the
   archive's home open between a GitHub release asset, Git LFS and an owned bucket, to be
   decided once the compressed size was known. It is **2.3 MB**. All three options were
   machinery for a problem that does not exist, and each reintroduces the thing being fixed:
   an external location that can rot or lose access. So `data/tables/*.csv.gz` is committed,
   `globalmart data fetch` does not exist, and `data verify` replaces it — offline, no
   credentials. ADR 007 records this, and amends ADR 003.

2. **Custody was taken from MotherDuck, not from S3.** `s3://gdc-services-aisolutions/...`
   is not readable with any credentials available here (`InvalidAccessKeyId`) — the risk row
   reading "the bucket is lost or access revoked before custody is taken, likelihood Low,
   impact Critical" had already happened. `gd_demo.globalmart` holds the same 214 tables and
   is what both published orgs actually query, which makes it better provenance anyway: data
   known to work, rather than an artifact believed to have produced it.

### Other things the implementation contradicted or added

3. **`fact_search_event` is generated inside the custody script, not at runtime.** The
   breakdown gave it its own runtime module (`search_event.py`). It is produced once,
   alongside the rest of the data, and committed like everything else — a runtime generator
   for one static table would be a second source of truth for bytes that are already in the
   repo. Its 4,000 rows draw customer ids from the real `dim_customer` and dates from the
   real order window, so they join; verified live (176 joins in a 5,000-row sample).

4. **`sql_channel_attribution` has been broken since it was written, and now runs.** It was
   the motivation for AC #4, but worth stating as an outcome: all 11 SQL datasets now execute
   against a loaded schema, wrapped in `SELECT * FROM (...) LIMIT 0` so the planner resolves
   every column without moving rows. `test_without_fact_search_event_the_check_fails` runs
   the negative case, so the passing check is not vacuous.

5. **Load ordering comes from the LDM, because the DDL has nothing to derive it from.** Zero
   `PRIMARY KEY` and zero `FOREIGN KEY` across all 215 tables — which is also why the load is
   truncate-then-load rather than upsert: there is no merge key.
   `test_the_ddl_declares_no_constraints` pins that so the strategy is revisited deliberately
   if constraints ever appear. The dataset ids are 1:1 with table names, so
   `prune.build_entity_index` (FEAT-004's) supplies the real dependency graph for free.

6. **A second profile exists, and it is the only one allowed to load.**
   `demo-cloud-rebuild` targets `globalmart_rebuild` in the same MotherDuck database.
   `demo-cloud` is explicitly `data_owned: false`, because its `globalmart` schema is what
   both published orgs read — a load there would empty the live demo data for its duration
   and leave it empty if it failed halfway. This is precisely what the flag is for.

7. **The warehouse drivers are an optional extra.** `uv sync --extra data`. Capturing,
   splitting and publishing never touch a warehouse, and duckdb alone is a ~15 MB wheel.

### Not done

- **Postgres was written but not exercised.** `loaders/postgres.py` implements the same
  protocol with `COPY ... FROM STDIN`, and `make_loader` selects it, but no Postgres target
  exists to run it against — the `local-inference` profile is still commented out. AC #10
  ("both warehouses load from the same archive and DDL") is therefore **unproven**, and is
  the one acceptance criterion this feature does not close. The adapter is small and the
  protocol is shared, so the risk is narrow, but it is real: CSV type and encoding quirks
  are exactly the class of thing that only shows up on the second warehouse.
