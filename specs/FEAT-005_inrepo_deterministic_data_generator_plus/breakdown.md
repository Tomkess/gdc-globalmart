## Technical Breakdown — FEAT-005: Own the GlobalMart data artifact and load it idempotently into MotherDuck or Postgres

> **Continuity with FEAT-001/002.** No new package and no new console script. This extends
> `src/globalmart/` (console script `globalmart`), reuses `TargetProfile` / `load_profile()` /
> `GlobalmartError` from `config.py`, the warehouse-adapter pattern from `datasource.py`,
> `read_tree()` from `layout_io.py` and `iter_sql_statements()` from `traversal.py`. Interfaces are
> pinned in `specs/CONTRACT.md`.

> **What this feature is not.** It does not generate data. The rows that load are the rows that exist
> today, byte-for-byte, with one exception: `fact_search_event`, which has never existed and must be
> synthesised so `sql_channel_attribution` resolves. Generation at large is FEAT-007.

> **The single invariant.** After this feature, no path from `git clone` to a populated warehouse
> touches `s3://gdc-services-aisolutions/`. The committed `data/archive-manifest.json` is the
> contract; the archive is interchangeable bytes that must match its digest.

---

### Components

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|
| `scripts/take_custody.py` | **One-shot, run once, then kept for provenance.** Downloads all 214 CSVs from the current bucket, records each file's row count and sha256, compresses them into `globalmart-data-v1.tar.zst`, and emits the first `data/archive-manifest.json`. Not part of the runtime CLI — it is the custody transfer, and after it succeeds the bucket is never read again. | New | S |
| `data/archive-manifest.json` | Committed contract. `{archive: {version, url, sha256, bytes, created}, tables: {<name>: {rows, sha256}}}`. Pins exactly which archive is correct and what it must contain. Reviewable: a change to it is a deliberate data change. | New (committed) | S |
| `src/globalmart/registry.py` | `TableSpec` (`name`, `columns: tuple[ColumnSpec, ...]`, `depends_on: tuple[str, ...]`) and `build_registry(ddl_path) -> TableRegistry`, parsing `data/ddl/globalmart.sql` with `sqlglot` into the 215 table specs plus the dependency graph inferred from `*_id` columns matching another table's key. `load_order()` and `truncate_order()` (its reverse) replace the predecessor's hardcoded 214-entry `LOAD_ORDER`, which is kept only as a cross-check fixture. | New | M |
| `src/globalmart/archive.py` | `fetch_archive(manifest, cache_dir) -> Path` — downloads to a gitignored cache, skips when the cached file already matches the pinned sha256, verifies after download, and is resumable. `verify_archive(path, manifest) -> VerifyReport` — checks the archive digest, then each table's row count and checksum after extraction. `extract_archive(path, dest) -> Path`. Any mismatch raises `ArchiveVerificationError` naming the table. | New | M |
| `src/globalmart/search_event.py` | The one synthesised table. Derives `fact_search_event`'s column set from `sql_channel_attribution`'s SQL statement (read via `traversal.iter_sql_statements()` from the parent tree), emits a DDL fragment appended to the registry, and generates rows whose foreign keys are drawn from the loaded dimension tables so joins actually resolve. Deliberately small and self-contained — it is the only place in this feature that invents data, and it says so in its module docstring. | New | M |
| `src/globalmart/loaders/base.py` | `WarehouseLoader` protocol: `apply_ddl(registry, schema)`, `census(schema) -> dict[str, int]`, `truncate(schema, tables)`, `load_table(schema, table, csv_path)`, `count(schema, table)`. One place defining what a warehouse must do, mirroring `datasource.py`'s adapter split. | New | S |
| `src/globalmart/loaders/motherduck.py` | MotherDuck/DuckDB adapter. `read_csv_auto` for loading; `DELETE FROM` if `TRUNCATE <schema>.<table>` proves unsupported in MotherDuck's dialect (verified in task 21, not assumed). | New | M |
| `src/globalmart/loaders/postgres.py` | Postgres adapter via `COPY ... FROM STDIN CSV HEADER` and `TRUNCATE ... CASCADE` in reverse dependency order. | New | M |
| `src/globalmart/dataload.py` | Orchestration. `load_data(profile, registry, data_dir, *, apply: bool = False) -> LoadResult` runs: profile validation → `data_owned` guard → registry-subset guard → census → apply DDL → truncate in reverse order → load in dependency order → post-load counts → SQL-dataset validation. Every write gated on `apply`; the default is a rehearsal that performs the guards, the census and the count comparison and writes nothing. | New | M |
| `src/globalmart/sqlcheck.py` | `validate_sql_datasets(model, registry, conn) -> list[SqlDatasetIssue]` — for each of the 11 SQL-backed datasets, statically checks every referenced table and column against the registry with `sqlglot`, then executes the statement against the loaded schema. A dataset referencing an unknown column is a named failure, which is exactly how `fact_search_event` should have been caught years ago. | New | M |
| `src/globalmart/config.py` | Extended: `warehouse_database: str \| None`, `data_owned: bool = False`, `data_cache_dir: Path = Path(".cache/globalmart-data")`, and `validate_for_load(profile) -> list[str]` mirroring FEAT-002's `validate_for_publish`. | Existing — modified | S |
| `src/globalmart/cli.py` | Adds the `data` group: `globalmart data fetch [--manifest data/archive-manifest.json] [--force]` (network read, local write, so `--dry-run` per the CLI convention) and `globalmart data load --target <profile> [--apply] [--only <table>]` (remote destructive write, so `--apply`). | Existing — modified | S |
| `config/targets.yaml` | `data_owned` and `warehouse_database` filled in per profile. `demo-cloud` → `gd_demo` / `globalmart`; `local-inference` → Postgres. | Existing — modified | S |
| `tests/fixtures/mini_archive/` | A 6-table archive (2 dimensions, 1 fact, 1 with a self-reference, 1 empty, 1 with an embedded comma and a UTF-8 name) plus its manifest, including a deliberately corrupt variant for the verification-failure tests. | New | M |
| `docs/data.md` | Where the archive lives, how custody was taken and when, how to fetch and load, what `data_owned` means, and the statement that a load is destructive with re-fetch as the restore path. | New | S |
| `.gitignore` | `.cache/globalmart-data/` and any extracted CSV tree. | Existing — modified | S |

---

### Data Model

**`data/archive-manifest.json`** — the committed contract:

```json
{
  "archive": {
    "version": "v1",
    "url": "<resolved in task 1>",
    "sha256": "…",
    "bytes": 0,
    "created": "2026-09-18",
    "source": "s3://gdc-services-aisolutions/local-inference/globalmart/ (custody taken 2026-09-18)"
  },
  "tables": {
    "dim_store":         {"rows": 0, "sha256": "…"},
    "fact_search_event": {"rows": 0, "sha256": "…", "synthesised": true}
  }
}
```

`synthesised: true` marks the one table this project invented, so a reader is never misled about
which rows are inherited.

**`TableSpec`** (`registry.py`, frozen): `name: str`, `columns: tuple[ColumnSpec, ...]`,
`depends_on: tuple[str, ...]`. **`ColumnSpec`**: `name: str`, `sql_type: str`, `nullable: bool`.
**`TableRegistry`**: `tables: Mapping[str, TableSpec]`, `load_order() -> tuple[str, ...]` (topological),
`truncate_order() -> tuple[str, ...]` (its reverse), `names() -> frozenset[str]`.

The DDL declares **zero primary keys** across all 215 tables, so `depends_on` is inferred from column
naming (`region_id` in `dim_store` → `dim_region`) and cross-checked against the predecessor's
`LOAD_ORDER`. A disagreement between the two is a task-time investigation, not a silent choice.

**`LoadResult`** (`dataload.py`, dataclass) — the report the CLI prints and the tests assert against:

| Field | Type |
|---|---|
| `target` | `str` |
| `schema` | `str` |
| `applied` | `bool` (`False` = rehearsal, nothing written) |
| `census_before` | `dict[str, int]` (row counts prior to any truncate) |
| `counts_after` | `dict[str, int]` |
| `tables_loaded` | `int` |
| `unknown_tables` | `tuple[str, ...]` (registry-subset guard; non-empty ⇒ refusal) |
| `sql_dataset_issues` | `tuple[SqlDatasetIssue, ...]` |
| `archive_version` | `str` |

**`SqlDatasetIssue`**: `dataset_id: str`, `kind: StrEnum(UNKNOWN_TABLE, UNKNOWN_COLUMN, EXECUTION_ERROR)`,
`detail: str`.

**Exceptions**, all `GlobalmartError` subclasses: `ArchiveVerificationError`, `UnknownTableError`,
`DataNotOwnedError`, `SqlDatasetError`.

No seeds, no scale factors, no generation rules — those belong to FEAT-007.

---

### Integration Points

- **The current S3 bucket** — read exactly once, by `scripts/take_custody.py`. No runtime code path
  reaches it, and a test asserts the bucket name appears nowhere under `src/`.
- **The archive host** — GitHub release asset, Git LFS or an owned bucket; decided in task 1 on
  measured size. `archive.py` takes a URL from the manifest and does not care which.
- **MotherDuck** (`duckdb` + `motherduck_token`) and **Postgres** (`psycopg`), through the loader
  adapters only.
- **FEAT-001** — `config.py`, `TargetProfile`, `read_tree()` for the SQL-dataset validation.
- **FEAT-002** — `datasource.py`'s adapter pattern (mirrored, not imported), `iter_sql_statements()`,
  the `--apply` gate, `validate_for_publish` as the shape for `validate_for_load`.
- **FEAT-006** — nothing computes without rows; `LoadResult.archive_version` lets a verification run
  record which data generation it measured.
- **ADR 002 / ADR 004** — `--apply` gates the load; the census and ownership guards stand in for a
  backup, with re-fetch as the restore path. That substitution is *stronger* here than it was under
  the generator plan: the archive is a real artifact to restore from.

---

### Test Strategy

Offline against `tests/fixtures/mini_archive/` and an in-memory DuckDB. `uv run pytest tests/ -x -q`.

**`tests/test_registry.py`** — 215 tables parsed from the DDL (214 + `fact_search_event`);
`load_order()` is topological and every dependency precedes its dependent; `truncate_order()` is its
exact reverse; the DDL-derived order is consistent with the predecessor's `LOAD_ORDER` fixture, with
any disagreement failing loudly rather than being resolved silently.

**`tests/test_archive.py`** — a cached archive matching the digest is not re-downloaded; a corrupt
archive raises `ArchiveVerificationError`; a table whose row count differs from the manifest is named;
a table whose checksum differs is named; extraction is idempotent.

**`tests/test_dataload.py`** — the one that matters: **loading twice yields identical row counts**
(the predecessor's doubling bug, asserted); a rehearsal (`apply=False`) performs the census and
writes nothing, with a test pinning the *default value* of `apply` to `False`; a profile without
`data_owned` raises `DataNotOwnedError` before any truncate; a schema holding an unknown table raises
`UnknownTableError` naming it; truncation happens in reverse dependency order; `census_before` is
populated before the first truncate.

**`tests/test_sqlcheck.py`** — all 11 SQL datasets validate against a registry built from the real
DDL; a dataset referencing a missing table is reported as `UNKNOWN_TABLE` (a regression test standing
in for `fact_search_event`); a missing column is `UNKNOWN_COLUMN`.

**`tests/test_search_event.py`** — the synthesised table's columns satisfy every column
`sql_channel_attribution` references; its foreign keys all resolve against the loaded dimensions;
generation is deterministic given the same inputs.

**`tests/test_no_hardcoded_identifiers.py`** — extended: no bucket name, host, schema or warehouse
identifier under `src/globalmart/`.

**Manual, once, user-initiated** — run `take_custody.py`; run `data fetch` on a clean cache; run
`data load --target demo-cloud` as a rehearsal, read the census; then with `--apply`; then again and
confirm identical counts; then the Postgres profile.

---

### Total Effort Estimate

| Scale | Meaning |
|---|---|
| S | A few hours |
| M | 1–3 days |
| L | 1–2 weeks |
| XL | More than a sprint — consider splitting the feature |

**Overall: M (4–6 days).** Down from the generator plan's 2–4 weeks. The work is the registry parse,
two warehouse adapters, the verification path and `fact_search_event`. The unknowns are the archive
size (which decides the host) and whether MotherDuck's dialect accepts `TRUNCATE` — both resolved by
a measurement rather than a design argument.

---

### Implementation Order

1. **`scripts/take_custody.py` and the first archive** — do this before anything else in the feature.
   Every other task is recoverable work; the bytes are not. Ends with a measured compressed size and
   therefore the archive-host decision.
2. **`data/archive-manifest.json`** — emitted by step 1, committed, reviewed.
3. **`registry.py` + `tests/test_registry.py`** — the DDL parse, dependency graph and orders,
   cross-checked against the predecessor's `LOAD_ORDER`.
4. **`tests/fixtures/mini_archive/`** — needed before the archive and load tests can exist.
5. **`archive.py` + `tests/test_archive.py`** — fetch, verify, extract.
6. **`config.py` extension + `config/targets.yaml`** — `data_owned`, `warehouse_database`,
   `validate_for_load`.
7. **`loaders/base.py` + `loaders/motherduck.py`** — the protocol and the first adapter, including
   the `TRUNCATE`-vs-`DELETE FROM` determination.
8. **`dataload.py` + `tests/test_dataload.py`** — orchestration, guards, census, the
   load-twice-no-doubling test.
9. **`loaders/postgres.py`** — the second adapter, proving the protocol was not MotherDuck-shaped.
10. **`search_event.py` + `tests/test_search_event.py`** — the synthesised table, built once the
    loader exists so its keys can be drawn from loaded dimensions.
11. **`sqlcheck.py` + `tests/test_sqlcheck.py`** — all 11 SQL datasets validated; confirms step 10
    actually closed the `sql_channel_attribution` gap.
12. **`cli.py` — the `data` group**, `.gitignore`, `docs/data.md`.
13. **The real runs (user-initiated)** — fetch on a clean cache, rehearse, apply, apply again for
    idempotency, then Postgres.
