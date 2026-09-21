---
kind: reference
title: SQL-backed datasets
scope: data-model
owner: analytics-eng
anchor: true
covers:
  datasets:
    - sql_*
---

# SQL-backed datasets

## The eleven of them

These datasets are defined by a SQL statement rather than by a physical table:
`sql_assortment_efficiency`, `sql_blended_daily_revenue`, `sql_campaign_roi`,
`sql_channel_attribution`, `sql_customer_ltv_snapshot`, `sql_inventory_health`,
`sql_loyalty_roi`, `sql_margin_bridge`, `sql_net_sales_summary`,
`sql_ops_efficiency_summary` and `sql_rfm_segments`.

## Why they exist

Each one encodes a calculation that is awkward or impossible in MAQL over the physical
model: a blend across several sources, a snapshot with its own as-of logic, or a bridge
between two figures. `sql_net_sales_summary` is the authoritative net-of-returns revenue
figure, `sql_margin_bridge` decomposes a margin movement into its causes, and
`sql_rfm_segments` assigns the recency, frequency and monetary quartiles the customer
dashboards display.

## The schema is a parameter, not a constant

Every SQL statement here is stored with `{{ datasource_schema }}` where the schema name
belongs, and that token is substituted at publish time from the target profile. It is never
stripped and never left templated — publishing a dataset whose statement still contains the
token produces a workspace that fails at query time rather than at publish time, which is
why the repository checks for it before writing.

## What this means when a number disagrees

A SQL dataset runs its own statement against the warehouse, so it can legitimately disagree
with a metric built over the physical facts: different filters, different join semantics,
different treatment of nulls. When `sql_net_sales_summary` and a sum over
`fact_order_header` differ, neither is broken — they are answering different questions, and
the SQL statement is the definition of record for which one.
