---
kind: reference
title: Fact tables
scope: data-model
owner: analytics-eng
covers:
  datasets:
    - fact_*
---

# Fact tables

## What a fact table is here

All 146 `fact_*` datasets record something measured: an event, a transaction, or a snapshot
taken on a schedule. Each one is table-backed, is joined to its dimensions by explicit
references, and is the source of the level-1 metrics named after it — `fact_absence` gives
`metric_l1_fact_absence_absence_hours`, and that naming is mechanical rather than curated.

## The three shapes

**Event and transaction facts** are one row per thing that happened: `fact_order_header`
(one order), `fact_order_line` (one line), `fact_returns`, `fact_shrinkage_event`,
`fact_price_adjustment`, `fact_fraud_alert`, `fact_chargeback`. Counting rows counts events.

**Snapshot facts** are one row per entity per period, and they must never be summed across
periods: `fact_headcount_snapshot`, `fact_inventory_snapshot_daily`, `fact_aged_inventory`.
Summing a headcount snapshot over twelve months gives twelve times the headcount.

**Pre-aggregated facts** arrive already summarised: `fact_daily_store_sales`,
`fact_daily_pnl`, `fact_product_performance_daily`, `fact_campaign_spend_daily`,
`fact_store_staffing_daily`, `fact_sales_by_hour`, `fact_footfall_hourly`. They agree with
the detail beneath them only if the detail is aggregated the same way.

## Two families documented separately

Fifty-two of the fact tables are derived score tables (`fact_*_attr_NN`) and fifteen are
e-commerce event tables (`fact_ecom_event_NN`). Both are large, uniform families with their
own conventions, so each has its own document rather than a line in this one.

## Where revenue lives, and why there are several

Revenue appears in `fact_order_header` (all orders), `fact_web_order_header` (online orders
only), `fact_daily_store_sales` (store-day totals), `fact_transaction_detail` (line-level
detail) and `sql_net_sales_summary` (net of returns and transfers). They are different
populations, not redundant copies, and a figure quoted without naming its source is
ambiguous.
