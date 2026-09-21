---
kind: reference
title: Hand-named metrics
scope: metrics
owner: analytics-eng
covers:
  metrics:
    - average_l1_bonus_cost
    - average_sales_amount_daily_store_sales
    - average_total_bonus_cost
    - average_total_nps_score
    - average_total_sales_amount_daily_store_sales
    - avg_order_value
    - avg_order_value_online
    - capex_budget_variance
    - maximum_total_chargeback_amount
    - maximum_total_kwh_consumed
    - minimum_total_competitor_price
    - minimum_total_headcount
    - minimum_weekly_total_headcount
    - sum_total_hours_worked_metric
---

# Hand-named metrics

## Not generated

Twenty metrics carry a chosen identifier rather than a `metric_lN_` one. Fourteen of them
are documented here; the other six are duplicates and evaluation fixtures, covered by *Duplicate
and evaluation metrics*. These are the metrics where the identifier was meant to be read.

## Averages, minima and maxima — the aggregations L1 does not do

Every generated level-1 metric is a `SUM`, so anything that needs a different aggregation is
here. `average_total_nps_score` averages `fact_nps_response.nps_score`, which is the
statistic anybody asking about NPS actually wants. `average_sales_amount_daily_store_sales`
averages a store-day total. `maximum_total_chargeback_amount` and
`maximum_total_kwh_consumed` take maxima; `minimum_total_competitor_price` and
`minimum_total_headcount` take minima.

## Two of them are worth knowing by name

`avg_order_value` is `SUM(revenue) / SUM(order_count)` over `fact_order_header` — average
order value across all channels. `avg_order_value_online` is the same calculation over
`fact_web_order_header`, so it is online orders only, and the two are not a total and a
part of a total: they come from different fact tables.

## Averaging a metric versus averaging a column

`average_total_bonus_cost` averages the fact column directly, while `average_l1_bonus_cost`
averages the level-1 metric over the same column. They read as the same thing and are not:
averaging a metric averages it over whatever attributes are in the query context, so the two
agree at the grain of the fact table and diverge everywhere else. When they disagree, the
column version is the row-level average and the metric version is the average of subtotals.

## The windowed one

`minimum_weekly_total_headcount` is the only hand-named metric with window logic:
`MIN((SELECT {L1 headcount} BY {transaction_date.week})) BY ALL {transaction_date.week}` —
the lowest weekly headcount across the whole window, not the minimum of the snapshot rows.
It is the example to copy when a question needs "the worst week".
