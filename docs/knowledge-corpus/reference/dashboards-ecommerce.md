---
kind: reference
title: E-commerce dashboards
scope: dashboards
owner: ecommerce-analytics
domains: [ecommerce]
covers:
  dashboards:
    - dashboard_002
    - dashboard_024
  visualizations:
    - viz_ecommerce_*
---

# E-commerce dashboards

## The two dashboards

- **`dashboard_002` — Online Sales & E-commerce Funnel.** Twelve tiles, all order count:
  unfiltered, In-Store channel, Online channel and North region, each by month, quarter and
  year.
- **`dashboard_024` — Seasonal Demand & Trends.** The same four order-count variants as
  single figures and as over-time series, plus one paired tile.

## This is the thin domain, deliberately

E-commerce has 2 dashboards and 24 visualizations, the smallest allocation in the workspace,
and every tile is a variant of one measure: order count. That makes it the weakest workspace
to ask a broad question of — and it is kept that way on purpose, because a nominally broad
"Overview" workspace that answers shallowly is a real pattern worth being able to
demonstrate rather than a gap worth filling.

## The funnel is named but not built

The title says funnel and no tile shows one. The fifteen `fact_ecom_event_*` tables that
would support a funnel exist in the model but feed none of these tiles, which draw on
`fact_web_order_header` order counts instead. Anyone asked for online funnel conversion here
should say the event tables exist and the funnel has not been assembled.

## In-Store on the e-commerce dashboard

Half the tiles are filtered to the In-Store channel, on a dashboard about online sales. That
is the generated level-3 filter set — In-Store, Online, North — applied uniformly across
every domain, not a modelling decision about e-commerce.

## Where the numbers come from

`fact_web_order_header` and `fact_web_order_line`, with `sql_channel_attribution` available
for channel attribution. Sliced by `dim_channel_master`, `dim_geography_region`,
`dim_utm_source` and `dim_acquisition_channel`.
