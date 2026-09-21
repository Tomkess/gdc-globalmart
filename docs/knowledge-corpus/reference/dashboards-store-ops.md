---
kind: reference
title: Store operations dashboards
scope: dashboards
owner: store-ops-analytics
domains: [store_ops]
covers:
  dashboards:
    - dashboard_012
    - dashboard_013
    - dashboard_026
  visualizations:
    - viz_store_ops_*
---

# Store operations dashboards

## The three dashboards

- **`dashboard_012` — Store Operations Efficiency.** Cost, staff hours, staff count,
  shrinkage amount, unit count, maintenance cost, downtime hours and visitor count.
- **`dashboard_013` — Staff Productivity & Scheduling.** Revenue per staff hour, cost by
  channel and region, and staff hours over time.
- **`dashboard_026` — Footfall & Store Traffic.** Shrinkage amount, unit count, maintenance
  cost and downtime hours across month, quarter and year.

## The one genuine efficiency ratio

`viz_store_ops_0264` is Revenue per Staff Hour, computed through
`sql_ops_efficiency_summary`. It is the workspace's clearest example of a productivity
measure that combines two subject areas correctly, and it is the tile to point at when asked
how store efficiency is measured here.

## Footfall is named and thin

`dashboard_026` is titled for footfall and store traffic; its tiles are shrinkage,
units, maintenance cost and downtime. The footfall data is real — `fact_footfall_hourly` and
`fact_store_visit_census` — and reaches only one tile, Visitor Count on `dashboard_012`.
Hourly footfall supports a time-of-day analysis through `dim_time_of_day_bucket` that no
dashboard performs.

## Shrinkage sits in two places

`fact_shrinkage_event` records shrinkage as events and `fact_write_off` records the
financial write-off. Store operations reports the first, finance the second, and they are
different populations rather than two views of one number — which is the usual reason an
operations shrinkage figure and a finance write-off figure do not match.

## Where the numbers come from

`fact_store_staffing_daily`, `fact_sales_by_hour`, `fact_footfall_hourly`,
`fact_store_visit_census`, `fact_shrinkage_event`, `fact_till_reconciliation`,
`fact_maintenance_request`, `fact_checkout_time`, plus `sql_ops_efficiency_summary`. Sliced
by `dim_store`, `dim_store_format`, `dim_store_department`, `dim_cashier`, `dim_shift_type`
and `dim_time_of_day_bucket`.
