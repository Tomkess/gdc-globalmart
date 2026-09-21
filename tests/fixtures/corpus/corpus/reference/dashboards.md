---
kind: reference
title: The two fixture dashboards
scope: dashboards
owner: analytics-eng
covers:
  dashboards:
    - dashboard_000
    - dashboard_mixed
  visualizations:
    - viz_customer_*
    - viz_sales_0000
    - viz_finance_0216
---

# The two fixture dashboards

## dashboard_000

The single-domain dashboard. Every tile on it belongs to one domain, which makes it the case
the splitter handles without any judgement: the dashboard and its visualizations travel into
exactly one child workspace.

## dashboard_mixed

The cross-domain dashboard, and the reason coverage is enforced rather than assumed. Its
tiles belong to more than one domain, so listing it in one domain pulls another domain's
visualizations along with it — reported as a cross-domain tile, never silently dropped.

## The tiles

`viz_customer_0096` and `viz_customer_0097` are customer-scoped; `viz_sales_0000` and
`viz_finance_0216` belong to sales and finance respectively. Each is a normal visualization
object with buckets and sorts, and none of them is a tile variant of another.
