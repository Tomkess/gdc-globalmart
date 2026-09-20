# The data

GlobalMart's rows live in this repo. All 215 tables, 174,372 rows, 2.3 MB gzipped under
`data/tables/`. A clone is the data — there is nothing to download and no credentials
needed to have it.

```bash
globalmart data verify                                  # offline: data + SQL datasets
globalmart data load --target demo-cloud-rebuild        # rehearsal
globalmart data load --target demo-cloud-rebuild --apply
globalmart data load --target <profile> --only dim_store,dim_product --apply
```

Loading needs the warehouse drivers, which are an optional extra:

```bash
uv sync --extra data
```

## Where it came from

Before this, the rows existed only in `s3://gdc-services-aisolutions/local-inference/globalmart/`
— a bucket this project does not own, filled by a generator that was never committed. Delete
the bucket and GlobalMart was unrecoverable.

Custody was taken on 2026-09-18 from **MotherDuck's `gd_demo.globalmart` schema**, not from
that bucket. Two reasons. The bucket is not readable with any credentials available here
(`InvalidAccessKeyId`), so the risk the spec listed as "access revoked before custody is
taken" had in effect already happened. And MotherDuck is the better source anyway: it is
what the published workspaces actually query, so it is data known to work rather than an
artifact believed to have produced it.

`scripts/take_custody.py` is the one-shot that did it. It is not part of the CLI; it is kept
so the provenance is auditable and the transfer repeatable.

## What is committed

| Path | What |
|---|---|
| `data/ddl/globalmart.sql` | 215 `CREATE TABLE` statements, `{schema_name}` templated |
| `data/tables/<table>.csv.gz` | One gzipped CSV per table |
| `data/table-manifest.json` | Per table: row count, column list, sha256, byte size |

The manifest hashes the **uncompressed** bytes. gzip embeds a timestamp, so a digest over
the compressed file would change every time anything was re-compressed and the integrity
check would be theatre.

The spec left the archive's home open — a GitHub release asset, Git LFS, or a bucket this
project controls. Measuring answered it: 174k rows compress to 2.3 MB, small enough that all
three options were solving a problem that does not exist. Committing removes the external
dependency entirely, which is what the feature was actually for.

## `fact_search_event`, the 215th table

`sql_channel_attribution` selects `FROM {{ datasource_schema }}.fact_search_event`. No DDL
and no CSV for that table has ever existed — the dataset was broken from the day it was
written, and nothing noticed, because a layout publishes fine whether or not its SQL can
run.

It is the one GlobalMart table whose rows are manufactured rather than inherited. Its
columns come from the statement's own references (`session_id`, `customer_id`,
`traffic_source`, `session_date`); its 4,000 rows are generated from one fixed seed, drawing
customer ids from the real `dim_customer` and dates from the window the real order data
covers, so every row joins. The manifest names it under `synthesised` so this never becomes
folklore.

## Loading is truncate-then-load

The predecessor ran `INSERT INTO {schema}.{table} SELECT * FROM read_csv_auto(...)` with no
truncate, so a second load left every table with twice the rows and no error at all. Here
every table is emptied immediately before it is filled: loading twice is loading once.

Not an upsert, because there is nothing to upsert on — the DDL declares zero `PRIMARY KEY`
and zero `FOREIGN KEY` across all 215 tables. `test_the_ddl_declares_no_constraints` pins
that, so if constraints are ever added the strategy gets revisited deliberately.

Order comes from the LDM's `references` graph rather than from the DDL, since the DDL has no
constraints to derive it from: dimensions load before the facts that point at them, and
truncation runs in reverse. No warehouse will reject a load for ordering reasons today; the
ordering is there so that if one ever does, it is already right.

## Why loading is guarded differently from publishing

A workspace publish takes a backup first (ADR 002). A warehouse load cannot — there is
nowhere to put a copy of a warehouse. ADR 004 substitutes three guards, all enforced before
a single row is deleted:

1. **`data_owned`** — the profile must declare, in `config/targets.yaml`, that the schema is
   this repo's to overwrite. Exactly one profile does: `demo-cloud-rebuild`. `demo-cloud`
   deliberately does not, because its `globalmart` schema is what the live workspaces read.
2. **Registry subset** — if the schema contains a table this repo does not know, the load is
   refused and the table is named. A mistyped `datasource_schema` then costs an error rather
   than someone else's data.
3. **Census** — every table's row count is read before anything is truncated and kept in the
   report, including in a rehearsal, so what was overwritten is knowable afterwards.

And `--apply` is still the only path to a write.

## Verified

Against `gd_demo.globalmart_rebuild`, an empty schema:

```
first  load: rows before 0        rows after 174,372   215 tables changed
second load: rows before 174,372  rows after 174,372     0 tables changed
```

That second line is the predecessor's defect, absent. It would have read 348,744.

All 11 SQL-backed datasets were then executed against the loaded schema — wrapped in
`SELECT * FROM (...) LIMIT 0`, so the planner resolves every column and join without moving
rows. All 11 pass, including `sql_channel_attribution`, which could not have run at all
before `fact_search_event` existed.

## The generator (FEAT-007)

The committed archive is the real GlobalMart data. The generator is an *alternative* source
for when you need a different size, not a replacement for it.

```bash
globalmart data generate --out .cache/gen --seed 42 --scale 1
globalmart data load --target demo-cloud-rebuild \
  --tables-dir .cache/gen/tables --manifest .cache/gen/table-manifest.json --apply
```

It refuses to write into `data/`. A generated variant must never silently become the
archive.

### What it guarantees

- **Determinism.** One seed, one output, byte for byte. Each table derives its own stream
  from `blake2b(seed, table_name)`, so adding a table or changing one table's row count does
  not shift every other table's values.
- **Referential integrity by construction.** Each table mints a key space as it is
  generated, in the registry's load order, and a foreign column draws from the target's
  minted keys. A value that was never minted cannot appear. Asserted across all 215 tables.
- **The real shape at scale 1.** Row counts come from `data/table-manifest.json`, so a
  generated dataset is directly comparable with the real one — 215 tables, 174,372 rows.
- **Dates inside the real window**, so existing date filters still match rows.
- **`--scale`**: facts linear, dimensions `sqrt` and never below their base. Facts carry the
  volume; multiplying twelve currencies by a hundred would be nonsense, and shrinking a
  dimension would drop keys the semantic layer expects.

### What it does not guarantee

**Plausibility.** The distributions are uniform and unremarkable. A generated dataset has
the right structure, the right keys and the right date range; it does not have believable
retail behaviour — no seasonality, no relationship between price and margin, no realistic
basket composition.

That boundary is deliberate. FEAT-007 was parked because inventing plausible retail data
with no consumer able to judge it is how a dataset quietly gets worse while every test still
passes. This is the substrate every use case shares; plausibility is a second body of work
and needs someone with a real need to say what "plausible" means.

**Two consequences worth stating.** Any eval with a baked-in expected answer is invalid
against generated data. And any analysis of the *numbers* is meaningless — only the
structure is meaningful.

### Verified, 2026-09-20

Generated at scale 1, loaded into `gd_demo.globalmart_rebuild`, and checked:

```
215 tables, 174,372 rows            matching the real archive exactly
all 11 SQL-backed datasets          execute
fact_order_header -> dim_customer   35,872 of 35,872 join
```

That load also caught a real bug: `hour_start` is an `INTEGER` whose name ends in `_start`,
and the generator had let the name override the declared type, writing a date into it. The
warehouse rejected it. The DDL's type is now authoritative and two tests pin that.
