## Technical Breakdown — FEAT-007: Synthetic GlobalMart data generator

> **Revived 2026-09-20 with no trigger named.** The scope is therefore the substrate every candidate
> trigger shares — determinism, referential integrity, scale — and not any one trigger's
> specialisation. What a trigger *would* add (seasonality, realistic price/margin relationships, a
> deliberately different variant shape) is left out, because inventing plausibility with no consumer
> to judge it is exactly the risk the spec parked this feature over.

> **Correction to the spec.** It says the prior design "exists in this repo's git history on the
> pre-2026-09-18 FEAT-005 breakdown". It does not: the initial commit already carries the
> post-split version, and `blake2b`/`KeySpace` appear nowhere but in FEAT-007's own spec. The design
> below is fresh. The ideas the spec attributes to that history are good ones and are adopted on
> their merits.

> **Nothing here duplicates FEAT-005.** The registry, the DDL parsing, the CSV-plus-manifest format,
> the loader and the SQL validation are all reused. This feature produces bytes in that format; it
> does not learn how to load them.

---

### Components

| Component | What it does | New/existing | Effort |
|---|---|---|---|
| `src/globalmart/generate.py` | The generator. `KeySpace` (a table's generated key values), `ColumnStrategy` (how one column's values are produced), `plan_columns(table, registry)` (choose a strategy per column from its name and SQL type), `generate_table(...)`, `generate_dataset(registry, *, seed, scale, out_dir) -> GenerationReport`. | New | L |
| `src/globalmart/registry.py` | One addition: `foreign_key_target(column_name, known_tables)` — resolve `<base>_id` to the table that owns it. Lives here because it is a fact about the schema, and `generate.py` should not be the second place that knows how tables relate. | Modified | S |
| `src/globalmart/dataload.py` | No logic change; `load_data` already takes `tables_dir` and `manifest_path`. | — | — |
| `src/globalmart/cli.py` | `globalmart data generate --out <dir> [--seed N] [--scale N]`, and `--tables-dir` / `--manifest` on `data load` so a generated set can be loaded. | Modified | S |
| `tests/test_generate.py` | Determinism, scale, referential integrity, date windows, row-count fidelity, registry-driven-ness. | New | M |
| `docs/data-custody.md` | A section on the generator: what it guarantees and — more importantly — what it does not. | Modified | S |

---

### Data Model

**`KeySpace`** — `table: str`, `column: str`, `values: tuple[str, ...]`. Built when a table is
generated and read by every table generated after it. This is what makes referential integrity
structural: a foreign column cannot hold a value that was never minted, because it draws from the
minted set rather than from a random generator that happens to use the same format.

**`ColumnStrategy`** (`StrEnum`): `OWN_KEY`, `FOREIGN_KEY`, `DATE`, `INTEGER`, `DECIMAL`, `NAME`,
`CODE`. Chosen by `plan_columns` from the column's SQL type and name suffix, never from a table
list. The suffix census that drove the mapping: 408 `_id`, 149 `DATE`, 121 `NUMERIC`, 101 `INTEGER`,
67 `_name`, then `_metric`/`_count`/`_amount`/`_cost`/`_revenue`.

**`GenerationReport`**: `tables: int`, `rows: int`, `seed: int`, `scale: float`,
`per_table: dict[str, int]`, `out_dir: Path`.

#### Seeding

One master `--seed`; each table derives its own stream from
`blake2b(f"{seed}:{table_name}", digest_size=8)`. Per-table sub-seeds rather than one shared
`Random` because a shared stream couples tables: adding a table, or changing one table's row count,
would shift every subsequent table's values and make two runs incomparable for no reason. With
sub-seeds, a table's output depends only on the seed, its own name and its own row count.

#### Row counts

At `--scale 1`, every table's row count is read from `data/table-manifest.json` — the real archive
is the shape reference, which is what makes generated data comparable with it. A table absent from
the manifest falls back to a default.

Scaling: a table is a **fact** if its name starts with `fact_`, otherwise a dimension.

    fact rows       = round(base * scale)
    dimension rows  = max(base, round(base * sqrt(scale)))

Facts carry the volume; dimensions are reference data, and multiplying 12 currencies by 100 to get
a bigger dataset would be nonsense. Dimensions never shrink below their scale-1 count, because
shrinking them would drop keys that the semantic layer's filters expect.

#### Column strategies

- **`OWN_KEY`** — the table's own identifier, `<n>`-suffixed and unique, recorded into its
  `KeySpace`. Identified as the first `_id` column whose base matches the table's own name, else
  the first `_id` column.
- **`FOREIGN_KEY`** — `<base>_id` resolving to a known table (`dim_<base>`, `<base>`, or a table
  whose own key is that column). Values are **drawn from that table's `KeySpace`**. A target that
  does not exist degrades to `CODE` rather than failing: the DDL declares no foreign keys, so an
  unresolvable `_id` is a naming coincidence, not an error.
- **`DATE`** — uniform within the window the real data covers, read once from the archive so
  existing date filters still match rows.
- **`INTEGER` / `DECIMAL`** — bounded ranges, with `_count`/`_qty` non-negative integers and
  `_amount`/`_cost`/`_revenue` two-decimal values. Unremarkable by design.
- **`NAME` / `CODE`** — deterministic readable strings derived from the table and row index.

#### Output

`<out>/tables/<table>.csv.gz` plus `<out>/table-manifest.json`, byte-for-byte the format
`dataload.verify_data` and `load_data` already consume, including the sha256-over-uncompressed-bytes
rule and `mtime=0` so gzip's timestamp does not break determinism. The manifest records `seed` and
`scale` under `source`, so a generated dataset says what produced it.

**Never `data/tables/`.** The generator refuses to write there. The committed archive is FEAT-005's
and a generated variant must not silently become it.

---

### Test Strategy

Offline, against the real DDL and manifest; a scaled-down run where a full one would be slow.

- **Determinism**: same seed and scale into two directories produce identical bytes; different seeds
  differ.
- **Fidelity**: at scale 1 every table's row count equals the manifest's exactly.
- **Scale**: at scale 4, `fact_order_line` is 4× and `dim_currency` is 2× (`sqrt`), never below its
  base.
- **Referential integrity** (the one that matters): for every generated table and every column with
  a resolvable target, the set of values is a subset of the target's key set. Asserted across all
  215 tables, not a sample — it is cheap and it is the property most easily broken by a later edit.
- **Dates**: every `DATE` value parses and lies inside the archive's window.
- **Registry-driven**: a DDL with a table the generator has never heard of produces that table.
- **Format**: `verify_data` accepts the generated output, so AC #6 holds without a warehouse.
- **Refusal**: pointed at `data/tables/`, the generator raises.

**Live, once**: generate at scale 1, load into `globalmart_rebuild`, execute the 11 SQL datasets.
That closes AC #6 and #7 against a real warehouse rather than a fixture.

---

### Implementation Order

1. `foreign_key_target` in `registry.py`, with its test — everything downstream depends on
   resolution being right.
2. `KeySpace`, `plan_columns` and the strategy assignment, tested against the real DDL.
3. `generate_table` and the value generators, with determinism tests.
4. `generate_dataset`: topological order, manifest emission, the `data/tables/` refusal.
5. Referential-integrity and scale tests across all 215 tables.
6. CLI: `data generate`, plus `--tables-dir`/`--manifest` on `data load`.
7. The live run: generate, load, execute the SQL datasets.
8. Docs.

---

### Total Effort Estimate

| Area | Effort |
|---|---|
| Registry resolution | S |
| KeySpace + strategies | M |
| Value generation + determinism | M |
| Dataset assembly + manifest | M |
| Tests | M |
| CLI + live run + docs | M |

**Overall: M, not the spec's `l`** — because the specialisations that made it `l` (plausible
distributions, seasonality, a second dataset shape) are explicitly out. The substrate is bounded:
the registry already knows the tables, FEAT-005 already owns the format and the loader, and what
remains is key management and value generation. If a real trigger later demands plausibility, that
is a second body of work on top of this, and it will have a consumer able to judge it — which is
precisely what this one lacks.
