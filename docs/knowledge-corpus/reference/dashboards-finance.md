---
kind: reference
title: Finance dashboards
scope: dashboards
owner: finance-analytics
domains: [finance]
anchor: true
covers:
  dashboards:
    - dashboard_010
    - dashboard_011
    - dashboard_025
  visualizations:
    - viz_finance_*
---

# Finance dashboards

## The three dashboards

- **`dashboard_010` — Daily Profit & Loss Summary.** Net revenue, amount, COGS, OpEx,
  approved budget, spent amount, recharge amount and budget amount, by month, quarter and
  year.
- **`dashboard_011` — Budget vs Actual Financials.** Net revenue and COGS by channel and
  region, including the Online-channel and North-region variants, plus over-time series.
- **`dashboard_025` — Gross Margin Bridge.** Approved budget, spent amount and recharge
  amount across all three grains.

## Net revenue is the figure to be careful with

`viz_finance_0216` is Net Revenue by Month, and net revenue in this workspace **excludes
intra-company transfers** — `fact_intercompany_recharge` is recharged internally and netted
out. That is why net revenue does not equal a sum of order revenue, and why a period
containing a large recharge shows the two diverging by exactly the recharge amount.

## Budget versus actual is three separate facts

Approved budget comes from `fact_budget_plan` and `fact_capex_project`, actual spend from
`fact_opex_transaction` and `fact_cogs_detail`, and the recharge from
`fact_intercompany_recharge`. There is no single budget-versus-actual fact table, so a
variance is a difference of metrics over different tables — `capex_budget_variance` is the
one pre-built example, approved budget minus spent amount on capital projects.

## The margin bridge is SQL-backed

`sql_margin_bridge` decomposes a margin movement, and `dashboard_025` is named for it. The
statement is the definition of record: the bridge's components are computed there rather
than in MAQL, so reconciling the bridge against the P&L tiles means reading the SQL, not
the metric tree.

## Where the numbers come from

`fact_daily_pnl`, `fact_cogs_detail`, `fact_opex_transaction`, `fact_budget_plan`,
`fact_capex_project`, `fact_intercompany_recharge`, `fact_write_off`, plus
`sql_net_sales_summary` and `sql_margin_bridge`. Sliced by `dim_gl_account`,
`dim_cost_center`, `dim_company_entity`, `dim_budget_version` and `dim_currency`.
