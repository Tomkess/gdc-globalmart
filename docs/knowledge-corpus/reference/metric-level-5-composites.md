---
kind: reference
title: Level-5 metrics — composites
scope: metrics
owner: analytics-eng
covers:
  metrics:
    - metric_l5_*
---

# Level-5 metrics — composites

## What they are

The 61 `metric_l5_NNNN` metrics are the deepest layer. Each adds a level-4
period-over-period difference to a ratio of two level-1 metrics:

    SELECT {metric/metric_l4_yoy_0000}
         + ({metric/metric_l1_total_order_count} / {metric/metric_l1_total_net_revenue})

Resolving one therefore touches five levels: L5 → L4 → L3 → L1 → fact column, plus two more
L1 metrics on the ratio side.

## They add quantities with different units

This is the honest description: an L5 metric sums a count difference and a dimensionless
ratio, or a currency difference and a ratio of currency to count. The result has no coherent
unit. The titles say so if read carefully — "YoY: Order Count — In-Store Channel (+Order
Count/Net Revenue)" is a year-over-year order-count change plus an orders-per-revenue
ratio — and the parenthesised suffix is the second term.

## Why they are in the workspace

They are here deliberately, as the hardest case for anything that has to explain a metric
rather than merely evaluate it. Evaluating one is trivial for the engine. Explaining one
requires traversing the whole chain and then saying plainly that the arithmetic is not
meaningful — which is a much better test of a semantic layer's documentation, and of an
assistant reading it, than a well-behaved revenue metric would be.

## Practical advice

Do not use an L5 metric to answer a business question. If one appears on a dashboard tile,
the tile is demonstrating depth rather than reporting a figure. When asked what an L5 metric
means, name its two terms, say that they have different units, and point at the L4 and the
L1 metrics underneath as the numbers that can actually be interpreted.
