---
kind: how_to
title: Refresh the warehouse data
scope: warehouse
owner: analytics-eng
anchor: true
---

# Refresh the warehouse data

## What "refresh" means here

GlobalMart's rows are **generated, not stored**. The repository commits the *contract* — the
215-table DDL in `data/ddl/globalmart.sql` and `data/table-manifest.json`, which records each
table's columns and row count — and the rows themselves are produced on demand. There is no
upstream system to pull from and nothing to wait for: a refresh is a regeneration.

## The four commands

    globalmart data verify                                  # the committed contract is coherent
    globalmart data generate --out <dir> --seed 20260920     # produce rows locally
    globalmart data load --target <profile> --apply           # truncate, then load
    globalmart data ensure --target <profile> --apply         # do both, only if needed

`data verify` is offline and checks that the DDL, the manifest and the layout agree.
`data ensure` is what automation runs: it regenerates and loads only when the warehouse is
empty or the data is older than `--max-age-days`, which defaults to 31.

## Keeping the window current

The generator takes `--start-date` and `--end-date` and defaults the end to today, which is
the point — a demo dataset whose newest row is eight months old makes every
"last month" question return nothing. `--seed` makes the output deterministic, so the same
seed and scale reproduce the same rows exactly, and `--scale` resizes: facts scale linearly
and dimensions by the square root, with `1.0` reproducing the committed row counts of
roughly 174,000 rows across 215 tables.

## The load is a truncate, and it is guarded

`data load` truncates every table it knows before loading. Three guards stand in front of
that, and all three are deliberate: the command is a read-only rehearsal unless `--apply`
is passed; the target profile must declare `data_owned: true`, so a profile that has not
opted in refuses outright; and a census of the target schema is taken and reported first.
A profile pointing at a warehouse somebody else owns cannot be truncated by accident.

## Which warehouse

The target profile names it. MotherDuck and Postgres are both supported, with
`warehouse_type` in `config/targets.yaml` choosing the adapter and `warehouse_database`
naming the database — `gd_demo` on the MotherDuck target. The schema is a parameter too, and
it is substituted into every SQL-backed dataset at publish time.
