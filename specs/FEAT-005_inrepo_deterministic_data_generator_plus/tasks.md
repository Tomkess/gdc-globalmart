## Tasks — FEAT-005: Own the GlobalMart data artifact and load it idempotently into MotherDuck or Postgres

> Appetite: `m`  ·  Generated: 2026-09-18 (rewritten after the generator was descoped to FEAT-007)

- [ ] 1. **Do this first — everything else in this feature is recoverable work, the bytes are not.** Write `scripts/take_custody.py`: download all 214 CSVs from `s3://gdc-services-aisolutions/local-inference/globalmart/` to a local directory, record each file's row count and sha256, and report the total raw and zstd-compressed size. Read-only against the bucket. **Requires explicit user approval to run — it reaches an external bucket with the project's AWS credentials.**
       Pre: none
       AC: #2

- [ ] 2. Decide the archive host from task 1's measured compressed size and record the decision in `docs/data.md`: a GitHub release asset on `Tomkess/gdc-globalmart` (simplest, ~2 GB per-asset ceiling), Git LFS (quota-bound), or an S3 bucket this project owns (no size limit, needs credentials in every consumer). Under a gigabyte, prefer the release asset.
       Pre: task 1 complete (compressed size known)
       AC: #1

- [ ] 3. Extend `scripts/take_custody.py` to pack the verified CSVs into `globalmart-data-v1.tar.zst` and emit `data/archive-manifest.json` in the shape pinned in the breakdown (`archive` block plus a per-table `{rows, sha256}` map). Upload the archive to the host chosen in task 2 and write its resolved URL and sha256 into the manifest. Commit the manifest; never the archive.
       Pre: task 2 complete (host decided)
       AC: #2

- [ ] 4. Create `src/globalmart/registry.py`: `ColumnSpec`, `TableSpec`, `TableRegistry`, and `build_registry(ddl_path) -> TableRegistry` parsing `data/ddl/globalmart.sql` with `sqlglot`. Resolve the `{schema_name}` placeholder before parsing. Infer `depends_on` from `*_id` columns matching another table's name-derived key.
       Pre: none (the DDL is already committed)
       AC: #9

- [ ] 5. Add `load_order()` (topological) and `truncate_order()` (its exact reverse) to `TableRegistry`, raising on a dependency cycle with the cycle named.
       Pre: task 4 complete (`depends_on` populated)
       AC: #9

- [ ] 6. Write `tests/test_registry.py`: 214 tables parsed from the committed DDL; `load_order()` places every dependency before its dependent; `truncate_order()` is the exact reverse; a synthetic cyclic DDL raises. Commit the predecessor's `LOAD_ORDER` as `tests/fixtures/predecessor_load_order.py` and assert the DDL-derived order is consistent with it — a disagreement fails the test naming both positions rather than silently preferring one.
       Pre: task 5 complete (both orders)
       AC: #9

- [ ] 7. Build `tests/fixtures/mini_archive/`: a 6-table archive (2 dimensions, 1 fact referencing both, 1 self-referencing table, 1 empty table, 1 table with an embedded comma and a UTF-8 name) with its manifest, plus a deliberately corrupt variant and a variant whose row count disagrees with the manifest.
       Pre: task 3 complete (manifest shape fixed)
       AC: #2

- [ ] 8. Create `src/globalmart/archive.py`: `fetch_archive(manifest, cache_dir) -> Path` downloading to a gitignored cache, skipping the download when the cached file already matches the pinned sha256, verifying after download, and resuming a partial transfer. Raise `ArchiveVerificationError` on digest mismatch.
       Pre: task 3 complete (manifest with URL and digest)
       AC: #1, #2

- [ ] 9. Add `extract_archive(path, dest) -> Path` and `verify_archive(path, manifest) -> VerifyReport` to `archive.py`, checking every table's row count and checksum after extraction and naming each mismatch.
       Pre: task 8 complete (`fetch_archive`)
       AC: #2

- [ ] 10. Write `tests/test_archive.py` against `mini_archive`: a cached archive matching the digest is not re-downloaded; the corrupt variant raises `ArchiveVerificationError`; the row-count-mismatch variant names the offending table; extraction is idempotent.
       Pre: task 9 complete (fetch, verify, extract), task 7 complete (fixtures)
       AC: #2

- [ ] 11. Extend `src/globalmart/config.py`: add `warehouse_database: str | None`, `data_owned: bool = False`, `data_cache_dir: Path = Path(".cache/globalmart-data")` to `TargetProfile`, plus `validate_for_load(profile) -> list[str]` mirroring FEAT-002's `validate_for_publish`. Fill the fields into `config/targets.yaml` for `demo-cloud` (`warehouse_database: gd_demo`, schema `globalmart`) and `local-inference` (Postgres).
       Pre: FEAT-002 task 2 complete (`TargetProfile`, `validate_for_publish` as the shape to mirror)
       AC: #6, #11

- [ ] 12. Extend `tests/test_config.py`: `data_owned` defaults to `False` when the key is absent; `validate_for_load` names every missing key; `config/targets.yaml` carries no secret values.
       Pre: task 11 complete (`validate_for_load`)
       AC: #6

- [ ] 13. Create `src/globalmart/loaders/base.py`: the `WarehouseLoader` protocol — `apply_ddl(registry, schema)`, `census(schema) -> dict[str, int]`, `truncate(schema, tables)`, `load_table(schema, table, csv_path)`, `count(schema, table)`.
       Pre: task 5 complete (registry supplies the orders the protocol is called with)
       AC: #10

- [ ] 14. Implement `src/globalmart/loaders/motherduck.py` against the protocol, using `read_csv_auto` for loading and `duckdb` with `motherduck_token` for the connection.
       Pre: task 13 complete (protocol)
       AC: #3, #10

- [ ] 15. Determine empirically whether MotherDuck's dialect accepts `TRUNCATE <schema>.<table>`; if not, implement `truncate` as `DELETE FROM`. Record the finding in a module comment so the next reader does not re-investigate. Test against an in-memory DuckDB where the dialect matches.
       Pre: task 14 complete (adapter skeleton)
       AC: #3

- [ ] 16. Create `src/globalmart/dataload.py` with `LoadResult`, `SqlDatasetIssue`, and `load_data(profile, registry, data_dir, *, apply: bool = False) -> LoadResult` sequencing: `validate_for_load` → `data_owned` guard → registry-subset guard → census → apply DDL → truncate in `truncate_order()` → load in `load_order()` → post-load counts. Every write gated on `apply`; the default is a rehearsal performing the guards, census and count comparison with zero writes.
       Pre: tasks 13, 11 complete (protocol and profile fields)
       AC: #3, #6, #7, #8

- [ ] 17. Add the two refusal guards to `dataload.py`: `DataNotOwnedError` when `profile.data_owned` is not `True`, raised before any truncate; `UnknownTableError` when the target schema holds a table absent from the registry, naming each unknown table (ADR 004).
       Pre: task 16 complete (`load_data` skeleton)
       AC: #6, #7

- [ ] 18. Write `tests/test_dataload.py` — the load-twice test first, since it is the predecessor's actual bug: load `mini_archive` into an in-memory DuckDB twice and assert every table's row count is identical after both runs. Then: `apply=False` performs the census and writes nothing, and a separate test pins the default value of `apply` to `False`; a profile without `data_owned` raises before any truncate; an unknown table in the schema raises naming it; truncation order is the reverse of load order; `census_before` is captured before the first truncate.
       Pre: tasks 16, 17 complete (orchestration and guards), task 7 complete (fixtures)
       AC: #3, #6, #7, #8, #9

- [ ] 19. Implement `src/globalmart/loaders/postgres.py` against the same protocol using `COPY ... FROM STDIN CSV HEADER` and `TRUNCATE ... CASCADE` in reverse dependency order. Writing this second proves the protocol was not shaped around MotherDuck.
       Pre: task 18 complete (protocol exercised end-to-end by the MotherDuck path)
       AC: #10

- [ ] 20. Extend `tests/test_dataload.py` to run the same load-twice and guard assertions through the Postgres adapter against a local Postgres (skipped cleanly when unavailable, so the suite stays green on a machine without one).
       Pre: task 19 complete (Postgres adapter)
       AC: #3, #10

- [ ] 21. Create `src/globalmart/search_event.py`: derive `fact_search_event`'s required column set from `sql_channel_attribution`'s SQL statement, read out of the parent tree via `read_tree()` and `traversal.iter_sql_statements()`. Emit a DDL fragment the registry appends, making 215 tables. The module docstring must state that this is the only invented data in the feature and why.
       Pre: task 4 complete (registry), FEAT-001 task 31 complete (real parent tree) or the committed export as a stand-in
       AC: #4

- [ ] 22. Add row generation to `search_event.py`: produce rows whose foreign keys are drawn from the already-loaded dimension tables so every join resolves, deterministic given the same inputs. Keep it small — this is one table, not a generation framework.
       Pre: task 21 complete (column set), task 16 complete (loader, so dimensions exist to draw keys from)
       AC: #4

- [ ] 23. Write `tests/test_search_event.py`: the derived column set satisfies every column `sql_channel_attribution` references; generated foreign keys all resolve against the fixture dimensions; two runs with the same inputs produce identical rows.
       Pre: task 22 complete (row generation)
       AC: #4

- [ ] 24. Decide whether `fact_search_event`'s rows are committed as a small CSV under `data/` or folded into the archive, and record the choice in `docs/data.md`. Committing keeps the one hand-made piece of data reviewable; folding it in keeps one artifact. Prefer committing if it is under a few megabytes.
       Pre: task 23 complete (row volume known)
       AC: #4

- [ ] 25. Create `src/globalmart/sqlcheck.py`: `validate_sql_datasets(model, registry, conn) -> list[SqlDatasetIssue]` — statically check each of the 11 SQL-backed datasets' referenced tables and columns against the registry with `sqlglot`, then execute each statement against the loaded schema, classifying failures as `UNKNOWN_TABLE`, `UNKNOWN_COLUMN` or `EXECUTION_ERROR`.
       Pre: task 4 complete (registry), FEAT-002 task 1 complete (`iter_sql_statements`)
       AC: #5

- [ ] 26. Wire `validate_sql_datasets` into `load_data` as the final step, populating `LoadResult.sql_dataset_issues`; a non-empty list fails the command with each issue named.
       Pre: tasks 25, 16 complete
       AC: #5

- [ ] 27. Write `tests/test_sqlcheck.py`: all 11 SQL datasets validate against a registry built from the real DDL (skipped cleanly if the real tree is absent); a dataset referencing a missing table is reported `UNKNOWN_TABLE` — the regression test standing in for the `fact_search_event` gap; a missing column is `UNKNOWN_COLUMN`.
       Pre: task 26 complete (wired in)
       AC: #4, #5

- [ ] 28. Add the `data` group to `src/globalmart/cli.py`: `globalmart data fetch [--manifest data/archive-manifest.json] [--force] [--dry-run]` (network read plus local write, so `--dry-run` per the CLI convention) and `globalmart data load --target <profile> [--apply] [--only <table>]` (remote destructive write, so `--apply`). Print the `LoadResult` report; exit 1 on any guard, verification or SQL-dataset failure.
       Pre: tasks 9, 26 complete (fetch and load both callable)
       AC: #1, #3, #6

- [ ] 29. Extend `tests/test_cli.py`: `data load` without `--apply` records zero writes against a fake loader; `--apply` performs them; a parser test pins that `data load` has no `--dry-run` flag and `data fetch` has no `--apply`, so the CLI convention cannot rot.
       Pre: task 28 complete (CLI wired)
       AC: #3

- [ ] 30. Extend `tests/test_no_hardcoded_identifiers.py` to assert no bucket name, host, schema or warehouse identifier appears under `src/globalmart/` — in particular that `gdc-services-aisolutions` appears nowhere outside `scripts/take_custody.py` and `docs/`.
       Pre: task 28 complete (all source modules written)
       AC: #11

- [ ] 31. Add `.cache/globalmart-data/` and any extracted CSV tree to `.gitignore`.
       Pre: task 8 complete (cache path fixed)
       AC: #1

- [ ] 32. Write `docs/data.md`: where the archive lives and why that host, how and when custody was taken (with the date and the source bucket), how to fetch and load, what `data_owned` means, the statement that a load is destructive with re-fetch as the restore path, and the note that `fact_search_event` is synthesised while every other table is inherited unchanged.
       Pre: tasks 2, 24 complete (host and search-event decisions recorded)
       AC: #1, #4

- [ ] 33. **Requires explicit user approval to run against a live warehouse.** Run `globalmart data load --target demo-cloud` as a rehearsal against `gd_demo.globalmart`; read the census and confirm the row counts match what the archive manifest expects.
       Pre: tasks 28, 31 complete (CLI proven offline); MotherDuck credentials
       AC: #8

- [ ] 34. **Requires explicit user approval — this truncates and reloads a live MotherDuck schema.** Run the same command with `--apply`, then a second time, and confirm every table's row count is identical after both runs. The rows are the same rows that were there before, so no eval baseline is invalidated by this load.
       Pre: task 33 complete (rehearsal clean)
       AC: #3

- [ ] 35. **Requires explicit user approval to run against a live warehouse.** Run `globalmart data load --target local-inference --apply` against Postgres and confirm all 215 tables load and all 11 SQL datasets validate.
       Pre: task 34 complete (MotherDuck path proven), task 19 complete (Postgres adapter)
       AC: #5, #10
