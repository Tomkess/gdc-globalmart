---
kind: reference
title: The miniature data model
scope: data-model
owner: analytics-eng
covers:
  datasets:
    - dim_*
    - fact_order_header
    - sql_assortment_efficiency
    - fiscal_date
---

# The miniature data model

## Dimensions

`dim_customer`, `dim_store` and `dim_channel_master` are the three dimensions this fixture
carries. Each is table-backed, keyed on its own natural id, and joined to the fact table by
a single reference rather than through a bridge.

## Facts

`fact_order_header` holds one row per order and is the only fact table here. Its grain is
the order, not the order line, so a metric that counts rows counts orders — which is the
usual source of a discrepancy against line-level figures.

## Derived and date datasets

`sql_assortment_efficiency` is SQL-backed, so its schema arrives as a parameter at publish
time rather than being baked in. `fiscal_date` is the date instance; the fiscal year starts
in February, which is why calendar-quarter comparisons against it are off by one month.
