---
kind: reference
title: Sales and NPS metrics
scope: metrics
owner: analytics-eng
anchor: true
covers:
  metrics:
    - average_total_sales_amount_daily_store_sales
    - average_sales_amount_daily_store_sales
    - average_total_nps_score
---

# Sales and NPS metrics

## Average sales amount

`average_sales_amount_daily_store_sales` averages the sales amount recorded on a single
store-day row. It is a row-level average and does not weight by transaction count, so a
store with one large basket and a store with fifty small ones contribute equally to it.

## Average total sales amount

`average_total_sales_amount_daily_store_sales` averages the pre-aggregated daily total for
each store. Net revenue excludes intra-company transfers, so this metric and the finance
ledger disagree by exactly the transfer volume in any period that contains one.

## Average NPS score

`average_total_nps_score` averages survey responses on the eleven-point scale as stored,
without converting to the promoter-minus-detractor form. Anyone comparing it to a published
NPS figure is comparing two different statistics that share a name.
