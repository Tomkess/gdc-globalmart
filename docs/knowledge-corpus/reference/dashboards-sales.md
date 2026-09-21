---
kind: reference
title: Sales dashboards
scope: dashboards
owner: sales-analytics
domains: [sales]
covers:
  dashboards:
    - dashboard_000
    - dashboard_001
    - dashboard_022
  visualizations:
    - viz_sales_*
---

# Sales dashboards

## The three dashboards

- **`dashboard_000` — Sales Performance Overview.** The entry point: discount amount, return
  amount, quantity returned, sales amount, transaction count, average transaction value,
  revenue and net revenue, each by month, quarter or year.
- **`dashboard_001` — Revenue by Channel & Region.** Paired-measure tiles: order count
  against net revenue change, net revenue against discount amount, and several cross-subject
  pairs reaching into loyalty, purchase orders and energy.
- **`dashboard_022` — Returns & Refunds Analysis.** More paired tiles, chaining average
  transaction value, revenue, net revenue, operating expense, gift-card transactions,
  loyalty points, price adjustments and till variance.

## What the titles promise and what the tiles show

`dashboard_001` and `dashboard_022` are titled for channel-and-region revenue and for
returns, and their tiles are largely generated measure pairs that reach across subject
areas — "Cost (Energy Consumption) vs Return Amount" sits on the sales dashboard because
the generator paired them, not because energy cost belongs to a returns analysis. Read the
tile titles rather than the dashboard title when interpreting these two.

## The 36 visualizations

`viz_sales_0000` to `viz_sales_0031` carry the content, twelve tiles per dashboard. The
numbering is sequential across the domain and not grouped by dashboard, so the tile range on
each dashboard is contiguous but the ranges are not aligned to round numbers.

## Where the numbers come from

Sales figures resolve to `fact_order_header`, `fact_order_line`, `fact_transaction_detail`,
`fact_daily_store_sales` and `fact_returns`, sliced by `dim_channel_master`,
`dim_geography_region` and `dim_store`. Net revenue specifically has an authoritative
SQL-backed source in `sql_net_sales_summary`, which nets returns and intercompany
recharges — and therefore does not match a plain sum of order revenue.
