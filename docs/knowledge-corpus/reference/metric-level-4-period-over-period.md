---
kind: reference
title: Level-4 metrics — period over period
scope: metrics
owner: analytics-eng
anchor: true
covers:
  metrics:
    - metric_l4_*
---

# Level-4 metrics — period over period

## What they are

The 400 `metric_l4_*` metrics are the largest level. Each takes a level-3 metric and
subtracts its own value in the previous period:

    SELECT {metric/metric_l3_0000_0}
         - (SELECT {metric/metric_l3_0000_0} FOR PREVIOUS ({label/transaction_date.month}))

The identifier says which comparison: `metric_l4_mom_NNNN` is month-over-month and
`metric_l4_yoy_NNNN` is year-over-year. Titles are prefixed "MoM:" or "YoY:" to match.

## They are differences, not percentages

An L4 metric returns the **absolute change** — this period minus last period, in the base
metric's own units. It is not a growth rate and not a percentage. "MoM: Order Count —
In-Store Channel" is a count of orders, positive or negative, and reading it as a percentage
overstates or understates by the whole base magnitude.

## The comparison period is always the calendar transaction date

`FOR PREVIOUS` is evaluated on `transaction_date` month or year in every one of these
metrics. That has three consequences worth knowing: the comparison is calendar-based even
though GlobalMart's fiscal year starts in February; it does not follow whatever date
attribute a dashboard filter offers; and in the first month or year of the data window the
previous period does not exist, so the metric returns null rather than the full current
value.

## Inherited filters

Because an L4 wraps an L3, it inherits that filter. Every L4 metric is therefore a change in
a *slice* — In-Store, Online or North — and none of them is a change in the unfiltered
total. There is no L4 metric over an unfiltered L1, so an overall month-over-month movement
has to be defined rather than looked up.
