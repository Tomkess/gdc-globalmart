---
kind: reference
title: Level-1 metrics — base aggregations
scope: metrics
owner: analytics-eng
anchor: true
covers:
  metrics:
    - metric_l1_*
---

# Level-1 metrics — base aggregations

## What they are

The 122 `metric_l1_*` metrics are the foundation of everything else: each one is a single
aggregation over a single fact column, and no level-1 metric references another metric.
Their MAQL is one line, for example
`SELECT SUM({fact/fact_absence.absence_hours})`.

## How they are named

Two naming forms are in use. Most are mechanical —
`metric_l1_fact_<dataset>_<column>`, as in
`metric_l1_fact_audit_finding_finding_count` — and their titles follow the same rule:
"Total Finding Count (Audit Finding)". A smaller set carries a shorter business name:
`metric_l1_total_order_count`, `metric_l1_total_net_revenue`,
`metric_l1_total_inventory_value`. Those short-named ones are the metrics the generated
higher levels reference most, so they are the ones worth recognising.

## Every one of them is a SUM

This is the single most important caveat in the metric layer. The generator applies `SUM`
uniformly, including over columns where a sum is not a meaningful statistic — scores,
snapshots, rates and indices all get summed. `metric_l1_fact_headcount_snapshot_total_headcount`
sums a snapshot, so over a year it returns roughly 365 times the headcount. Reading "Total"
in a level-1 title as "sum of the column" is always correct; reading it as "the total" is
not.

## Using them

A level-1 metric is the right starting point for a new question: it is unfiltered, it has
no period logic, and its definition is one hop from the warehouse. Filter it or compare it
yourself rather than hunting for a generated L3 or L4 that happens to match what you
wanted — there are 766 of those and finding the right one is slower than writing the filter.
