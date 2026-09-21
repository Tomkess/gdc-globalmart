---
kind: reference
title: Product dashboards
scope: dashboards
owner: merchandising-analytics
domains: [product]
covers:
  dashboards:
    - dashboard_003
    - dashboard_023
    - dashboard_028
  visualizations:
    - viz_product_*
---

# Product dashboards

## The three dashboards

- **`dashboard_003` — Product Performance & Margins.** Units sold, margin, markdown amount,
  planogram compliance score, out-of-stock days, range-review decision count, average rating
  and review count.
- **`dashboard_023` — Competitor Pricing Intelligence.** Units sold and margin — including
  margin from the Daily Product Performance source and the North-region variant — plus
  markdown over time and compliance score.
- **`dashboard_028` — Cross-sell & Product Affinity.** Out-of-stock days, decision count,
  average rating and review count across month, quarter and year.

## Margin has two sources that do not match

`viz_product_0073` is titled "Margin (Daily Product Performance data)" and `viz_product_0074`
is plain "Margin". The first comes from `fact_product_performance_daily`, which is
pre-aggregated to product-day; the second resolves through the order line detail. They
disagree wherever the daily aggregation was computed with different filters, and the tile
titles are the only indication of which is which.

## Competitor pricing and affinity are named but thin

`dashboard_023` is titled for competitor pricing and shows units sold and margin; the actual
competitor data is in `fact_competitor_pricing` with `minimum_total_competitor_price` as the
only pre-built metric over it. `dashboard_028` is titled for cross-sell affinity and shows
ratings and range-review decisions; affinity itself lives in `fact_product_attr_06` Product
Cross-sell Score and is not displayed.

## Where the numbers come from

`fact_product_performance_daily`, `fact_order_line`, `fact_markdown_event`,
`fact_planogram_compliance`, `fact_range_review_outcome`, `fact_product_rating`,
`fact_competitor_pricing`, plus `sql_assortment_efficiency`. Sliced by `dim_product`,
`dim_category_l1`, `dim_category_l2`, `dim_brand`, `dim_private_label`, `dim_season` and
`dim_product_lifecycle_stage`.
