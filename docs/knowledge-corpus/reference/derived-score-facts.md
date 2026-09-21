---
kind: reference
title: Derived score facts
scope: data-model
owner: analytics-eng
covers:
  datasets:
    - fact_customer_attr_*
    - fact_fin_attr_*
    - fact_hr_attr_*
    - fact_inv_attr_*
    - fact_loyalty_attr_*
    - fact_mkt_attr_*
    - fact_ops_attr_*
    - fact_product_attr_*
    - fact_re_attr_*
    - fact_risk_attr_*
---

# Derived score facts

## One family, ten subject areas

Fifty-two fact tables follow the pattern `fact_<area>_attr_NN` and hold a derived score
rather than a measured quantity. The areas are customer (6), finance (8), HR (5),
inventory (8), loyalty (3), marketing (5), store operations (7), product (8), real
estate (6) and risk (2). The numeric suffix is a slot, not a rank — `fact_hr_attr_00` is
Employee Performance Score because it was the first one defined, not because it matters most.

## What each one is

The title carries the meaning and the identifier does not, so these are the tables where
reading the title is mandatory. Examples: `fact_customer_attr_00` is Customer LTV Score,
`fact_customer_attr_01` is Customer Churn Risk Score, `fact_fin_attr_00` is Budget Variance
Score, `fact_inv_attr_03` is Inventory Shrinkage Risk, `fact_risk_attr_00` is Fraud Risk
Score, and `fact_product_attr_05` is Product Price Elasticity.

## How to treat a score

A score is a model output. It is unitless, its scale is not documented by the model itself,
and it is comparable across entities but not across score families. Averaging two different
scores together produces a number with no meaning, and so does summing any of them — the
level-1 metrics over these tables use SUM because the metric generator applies SUM
uniformly, which is a property of the generator rather than a claim about the statistic.

## Why they exist in a demo dataset

They give the workspace realistic breadth: a real retail semantic layer carries dozens of
model-produced scores beside its measured facts, and an assistant that has only ever seen
clean additive measures answers questions about them badly.
