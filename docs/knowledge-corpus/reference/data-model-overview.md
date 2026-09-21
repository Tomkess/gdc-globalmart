---
kind: reference
title: GlobalMart data model — overview
scope: data-model
owner: analytics-eng
---

# GlobalMart data model — overview

## What the model contains

GlobalMart's parent workspace holds **227 datasets**: 146 fact tables, 68 dimensions, 11
SQL-backed datasets and 2 date instances. On top of them sit 1,091 metrics, 384
visualizations and 32 dashboards. Every one of those objects is defined in the repository
rather than in the workspace, so the workspace is an output and the repository is the source.

## How to find your way around

Identifiers carry their type as a prefix, and that convention is load-bearing rather than
cosmetic — the documentation, the domain manifest and the coverage gate all rely on it.

- `fact_*` — a measured event or a periodic snapshot. See *Fact tables*.
- `dim_*` — an entity you slice by. See *Dimension tables*.
- `sql_*` — a dataset defined by a SQL statement rather than a physical table. See *SQL datasets*.
- `transaction_date`, `fiscal_date` — the two date instances. See *Date datasets and the fiscal year*.
- `metric_l1_*` … `metric_l5_*` — the five-level metric hierarchy, one document per level.
- `viz_<domain>_NNNN`, `dashboard_NNN` — analytical content, documented per domain.

## Grain is the thing to check first

Most disagreements between two GlobalMart numbers are grain disagreements, not calculation
errors. `fact_order_header` is one row per order and `fact_order_line` is one row per line,
so a count of rows means different things in each; `fact_daily_store_sales` is already
aggregated to store-day, so summing it and summing the transactions beneath it are two
different questions. Each fact table's document states its grain, and that is the first
thing to read before comparing two figures.

## What is not in the model

There are no aggregate-awareness tables, no materialised roll-ups and no semantic joins
across the domain workspaces. The twelve domain workspaces are pruned copies of this parent,
not peers that can be queried together — a question spanning two domains is answered by
asking both and combining the answers, never by a join.
