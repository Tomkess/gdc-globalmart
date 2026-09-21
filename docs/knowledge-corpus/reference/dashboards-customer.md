---
kind: reference
title: Customer dashboards
scope: dashboards
owner: customer-analytics
domains: [customer]
covers:
  dashboards:
    - dashboard_004
    - dashboard_017
    - dashboard_027
  visualizations:
    - viz_customer_*
---

# Customer dashboards

## The three dashboards

- **`dashboard_004` — Customer Segmentation & Lifetime Value.** Twelve tiles covering points
  redeemed, customer event count and value, order amount and NPS score, by month, quarter
  and year.
- **`dashboard_017` — Customer Feedback & NPS.** Despite the title, this is the dashboard
  carrying the RFM and lifetime-value tiles: lifetime revenue, average order value, and the
  recency, frequency and monetary quartiles from `sql_rfm_segments`.
- **`dashboard_027` — Customer Acquisition & Churn.** Event value, points and order amount
  across all three grains.

## The two most useful tiles

`viz_customer_0110`, `0111` and `0112` are the RFM quartiles — recency, frequency and
monetary — and they are the only place in the workspace where the RFM segmentation surfaces.
`viz_customer_0108` (Lifetime Revenue) and `viz_customer_0109` (Average Order Value) sit
beside them and come from `sql_customer_ltv_snapshot`.

## Segmentation and churn live in score tables, not on these dashboards

The customer scores — `fact_customer_attr_00` Customer LTV Score, `attr_01` Churn Risk
Score, `attr_02` Purchase Propensity, `attr_03` Product Affinity, `attr_04` Channel
Preference, `attr_05` Promotion Response — are in the model but are not what these tiles
display. A question about churn risk needs those tables, and no tile answers it directly.

## A title-versus-content caution

`dashboard_004` is titled for segmentation and lifetime value while its tiles are largely
loyalty points and customer events; `dashboard_017` is titled for feedback and NPS while
carrying the lifetime-value tiles. The two are effectively swapped relative to their names.
This is generated content, and the tile titles are the reliable description.

## Where the numbers come from

`fact_customer_event`, `fact_customer_feedback`, `fact_nps_response`,
`fact_loyalty_points_redeemed` and `fact_order_header`, sliced by `dim_customer`,
`dim_customer_segment`, `dim_household` and `dim_lifecycle_stage`.
