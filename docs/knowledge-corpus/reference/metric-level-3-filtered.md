---
kind: reference
title: Level-3 metrics — filtered variants
scope: metrics
owner: analytics-eng
covers:
  metrics:
    - metric_l3_*
---

# Level-3 metrics — filtered variants

## What they are

The 366 `metric_l3_NNNN_K` metrics are level-1 metrics with one filter applied:
`SELECT {metric/metric_l1_total_order_count} WHERE {label/dim_channel_master.channel_type} IN ("In-Store")`.
The trailing `_K` is the filter variant — `_0`, `_1` and `_2` of the same base metric are
the same quantity filtered three different ways.

## The three filters in use

Almost every L3 metric uses one of three filters, and they are the same three throughout:

- `channel_type IN ("In-Store")` — titled "— In-Store Channel"
- `channel_type IN ("Online")` — titled "— Online Channel"
- `region_name IN ("North")` — titled "— North Region"

So "Order Count — North Region" is order count for the North region and for nothing else.
There is no South, East or West variant, and no combination of channel and region.

## Reading the title as the definition

The em-dash suffix in the title is the filter, reliably. If a title has no suffix it is not
an L3 metric. This makes the L3 layer the one place where the generated titles are genuinely
dependable: the arithmetic is one filter on one base metric, and the title names both.

## When to use one, and when not to

Use an L3 metric when the filter is exactly one of the three above; it saves defining it. Do
not use one as a component of your own calculation without checking its base metric, because
a hidden `WHERE` inside a metric you are dividing by is the classic source of a ratio that
cannot be reconciled with its parts. And do not combine an L3 with a dashboard filter on the
same attribute — the metric's own filter wins its slice, and the interaction is confusing
rather than additive.
