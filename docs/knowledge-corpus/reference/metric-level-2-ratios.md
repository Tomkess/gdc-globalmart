---
kind: reference
title: Level-2 metrics — ratios
scope: metrics
owner: analytics-eng
covers:
  metrics:
    - metric_l2_*
---

# Level-2 metrics — ratios

## What they are

The 122 `metric_l2_cross_NNNN` metrics each divide one level-1 metric by another:
`SELECT {metric/metric_l1_total_order_count} / {metric/metric_l1_total_net_revenue}`.
Nothing else happens in them — no filter, no period logic, no null handling.

## The identifier carries no meaning

`metric_l2_cross_0000` tells you the level and the position in the generated sequence, and
nothing about the numerator or the denominator. The title does carry that: "Order Count per
Net Revenue" means order count divided by net revenue, in that order. Reading the title is
the only way to know what an L2 metric computes without opening its MAQL.

## They are combinatorial, so most are not useful

The generator pairs level-1 metrics across subject areas, which produces ratios such as
"Inventory Value per Discount Amount (Loyalty Redemption at POS)". That is a well-formed
division of two real quantities and it answers no question anybody has. A handful are
genuinely meaningful — revenue over order count is average order value — and the rest exist
to populate the layer. Do not infer from an L2 metric's existence that the ratio is tracked.

## Two arithmetic hazards

There is no denominator guard: where the denominator is zero or null for a slice, the metric
returns null for that slice rather than zero, and a chart may simply show a gap. And because
both operands are sums, the ratio is a ratio of totals rather than an average of ratios —
for a per-store or per-day figure, those differ, and the ratio of totals is the one this
layer gives you.
