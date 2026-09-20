## Tasks — FEAT-007: Synthetic GlobalMart data generator

> Appetite: `l` as specified; the breakdown argues `m` for the substrate-only scope.
> Generated: 2026-09-20

- [x] 1. Add `foreign_key_target(column_name, known_tables) -> str | None` to `registry.py`: resolve `<base>_id` to `dim_<base>`, `<base>`, or a table whose own key column is exactly that name; `None` when nothing resolves. Lives in the registry because it is a fact about the schema, not about generation.
       AC: #5, #11

- [x] 2. Test `foreign_key_target` against the real DDL: `customer_id` resolves to `dim_customer`; a column with no matching table resolves to `None`; the count of resolvable id columns is pinned so a registry change that breaks resolution fails loudly.
       Pre: task 1
       AC: #5

- [x] 3. Create `src/globalmart/generate.py` with `GenerationError(GlobalmartError)`, `ColumnStrategy` (`StrEnum`), `KeySpace`, `ColumnPlan` and `GenerationReport`. Constants for the default row count and the fallback date window.
       AC: #11

- [x] 4. Implement `plan_columns(table, known_tables) -> tuple[ColumnPlan, ...]`: choose a strategy per column from SQL type and name suffix. Own key = the first `_id` column whose base matches the table name, else the first `_id` column. Foreign key = a resolvable `_id`. Then `DATE`, numeric by suffix, `NAME`, `CODE`. No table or column name appears in the code.
       Pre: tasks 1, 3
       AC: #10, #11

- [x] 5. Test `plan_columns` against the real DDL: every one of the 215 tables plans without error; `dim_customer.customer_id` is `OWN_KEY`; `fact_order_header.customer_id` is `FOREIGN_KEY` targeting `dim_customer`; a `DATE` column is `DATE`; an unresolvable `_id` degrades to `CODE` rather than raising.
       Pre: task 4
       AC: #5, #10

- [x] 6. Implement per-table sub-seeding: `table_seed(seed, table_name)` via `blake2b(digest_size=8)`. A shared stream would couple tables — adding one, or changing one's row count, would shift every table after it and make two runs incomparable for no reason.
       Pre: task 3
       AC: #2, #3

- [x] 7. Implement the value generators per strategy, each taking a seeded `Random`: unique own keys, foreign keys drawn **only** from the target's `KeySpace`, dates uniform inside the window, bounded integers and two-decimal amounts, deterministic readable names and codes.
       Pre: tasks 4, 6
       AC: #2, #5, #8

- [x] 8. Implement `row_count_for(table, base_counts, scale)`: facts (`fact_` prefix) linear in scale, dimensions `max(base, round(base * sqrt(scale)))`. Base counts come from `data/table-manifest.json`, so scale 1 reproduces the real archive's shape exactly.
       Pre: task 3
       AC: #1, #4

- [x] 9. Implement `generate_table(table, plan, *, rows, keyspaces, seed)` returning CSV bytes and the table's own `KeySpace`.
       Pre: tasks 7, 8
       AC: #1, #2, #5

- [x] 10. Implement `generate_dataset(registry, *, seed, scale, out_dir, base_counts)`: iterate in the registry's **load order** so a target's keys exist before anything references them, write `<out>/tables/*.csv.gz` with `mtime=0`, and emit `<out>/table-manifest.json` in FEAT-005's exact format with `seed` and `scale` recorded under `source`.
       Pre: task 9
       AC: #1, #2, #6

- [x] 11. Implement the refusal: `generate_dataset` raises if `out_dir` resolves to the committed `data/` directory. A generated variant must never silently become the archive.
       Pre: task 10
       AC: #9

- [x] 12. Write `tests/test_generate.py` part 1 — determinism and fidelity: two runs with one seed produce byte-identical output; two seeds differ; at scale 1 every table's row count equals the manifest's; the refusal fires.
       Pre: tasks 10, 11
       AC: #1, #2, #3, #9

- [x] 13. Write `tests/test_generate.py` part 2 — **referential integrity across all 215 tables**: for every generated table and every `FOREIGN_KEY` column, the set of emitted values is a subset of the target's key set. Across all tables, not a sample: it is cheap and it is the property a later edit most easily breaks.
       Pre: task 12
       AC: #5

- [x] 14. Write `tests/test_generate.py` part 3 — scale and dates: at scale 4 a fact table is 4× and a small dimension is `sqrt`-scaled and never below base; every `DATE` value parses and falls inside the archive's window.
       Pre: task 12
       AC: #4, #8

- [x] 15. Write `tests/test_generate.py` part 4 — format and registry-driven-ness: `dataload.verify_data` accepts the generated output unchanged (AC #6 without a warehouse); a DDL carrying a table the generator has never seen produces that table.
       Pre: task 12
       AC: #6, #10

- [x] 16. Add `globalmart data generate --out <dir> [--seed N] [--scale N]` to `cli.py`, and `--tables-dir` / `--manifest` to `data load` so a generated dataset can be loaded without touching the committed archive. Local-file writer, so no `--apply`.
       Pre: task 10
       AC: #6, #9

- [x] 17. Extend `tests/test_cli.py`: `data generate` writes into the given directory and exits 0; it refuses `data/`; `data load --tables-dir` accepts a generated directory.
       Pre: task 16
       AC: #6, #9

- [x] 18. Extend `tests/test_no_hardcoded_identifiers.py` (or add a check in `test_generate.py`): no table name and no column name from the DDL appears in `generate.py`.
       Pre: task 16
       AC: #11

- [x] 19. **Live, once**: generate at scale 1 into a scratch directory, load it into `globalmart_rebuild` with `data load --tables-dir`, and execute all 11 SQL-backed datasets against it. This closes AC #6 and #7 against a real warehouse rather than a fixture. Restore the real archive afterwards.
       Pre: tasks 16, 17
       AC: #6, #7

- [x] 20. Extend `docs/data-custody.md` with a generator section: how to run it, what it guarantees (shape, keys, dates, determinism) and — the part that matters — what it does not (plausible distributions, seasonality, believable retail behaviour), plus the note that eval ground truth baked against the real archive is invalid against generated data.
       Pre: task 19
       AC: #9
