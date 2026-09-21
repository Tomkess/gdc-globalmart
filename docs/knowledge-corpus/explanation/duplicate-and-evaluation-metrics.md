---
kind: explanation
title: Duplicate and evaluation metrics
scope: metrics
owner: analytics-eng
anchor: true
covers:
  metrics:
    - average_l1_bonus_cost_duplicate
    - average_total_bonus_cost_variant
    - average_total_sales_amount_daily_store_sales_copy
    - maximum_total_chargeback_amount_from_total_metric
    - custom_max_total_chargeback
    - rev_per_order_evaltest
---

# Duplicate and evaluation metrics

## Six metrics that exist to be confusing

These are deliberate. GlobalMart is used to evaluate AI assistants and search ranking, and a
workspace where every metric has one obvious name tests nothing. So six metrics exist
specifically as near-duplicates and fixtures, and anyone reading the metric list should know
which they are rather than assume a mess.

## The three duplicates

`average_l1_bonus_cost_duplicate` has MAQL identical to `average_l1_bonus_cost`.
`average_total_sales_amount_daily_store_sales_copy` is identical to its original.
`average_total_bonus_cost_variant` is the interesting one: it is titled as a variant of
`average_total_bonus_cost`, but its MAQL averages the level-1 *metric* while the original
averages the fact *column*. Same title family, genuinely different calculation — which is
exactly the trap a metric search should not fall into.

## Two that differ only in their source

`maximum_total_chargeback_amount` takes the maximum of the fact column;
`maximum_total_chargeback_amount_from_total_metric` takes the maximum of the level-1 metric
over that column. The pair exists to ask whether a reader can tell that "from total metric"
changes the aggregation level.

## Two with poor identifiers, on purpose

`custom_max_total_chargeback` has no title — its title field is the identifier itself — so
anything that relies on titles for display shows a raw identifier to a user.
`rev_per_order_evaltest` is `SUM(revenue) / SUM(order_count)`, which is exactly
`avg_order_value` under a name that says "test". Both are reminders that a real workspace
accumulates objects whose names were never meant to be read by anyone.

## How to treat them in an answer

Name them as duplicates rather than picking one. Asked for "average bonus cost", the useful
answer says there are three candidates, that two are identical and one averages at a
different level, and asks which is meant — that is the correct behaviour in a real workspace
too, and it is the behaviour these six objects exist to provoke.
