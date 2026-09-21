---
kind: explanation
title: Why bonus cost is averaged twice
scope: metrics
owner: finance-analytics
domains: [finance]
covers:
  metrics:
    - average_l1_bonus_cost
    - average_total_bonus_cost
---

# Why bonus cost is averaged twice

## Two averages, two questions

`average_l1_bonus_cost` averages the level-one component only; `average_total_bonus_cost`
averages the whole bonus. They exist separately because compensation review asks about the
guaranteed component and budgeting asks about the total, and a single metric answering both
questions would answer neither correctly.

## Why the totals do not reconcile

The level-one average is not a share of the total average. Level-one is present on every
eligible row, whereas the remaining components are sparse, so the two averages run over
different denominators and their difference is not a meaningful quantity.
