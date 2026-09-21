---
kind: reference
title: E-commerce event facts
scope: data-model
owner: analytics-eng
domains: [ecommerce]
covers:
  datasets:
    - fact_ecom_event_*
---

# E-commerce event facts

## The fifteen event tables

`fact_ecom_event_00` through `fact_ecom_event_14` are one table per tracked online event,
in roughly funnel order: Page View, Product View, Add to Cart, Remove from Cart, Wishlist,
Site Search, Checkout Start, Payment Entry, Order Confirmation, Product Review, Live Chat,
Coupon Applied, Product Comparison, Newsletter Signup, Push Notification.

## One table per event, not one table with a type column

This is modelled as fifteen tables rather than one event table with an event-type dimension.
The consequence for anyone querying it: there is no single "events" metric to filter, so a
funnel is assembled from several metrics rather than from one metric sliced by type. Add to
Cart and Checkout Start are different datasets and cannot be compared with a filter.

## The funnel is not enforced

Nothing in the model guarantees that a row in Order Confirmation has a matching row in
Checkout Start, or that the counts decline monotonically down the funnel. The data is
generated per table independently, so drop-off rates computed from these tables are
arithmetically correct and behaviourally meaningless. Treat them as a structural example of
funnel modelling, not as a source of conversion insight.

## What feeds from them

The e-commerce dashboards (`dashboard_002`, `dashboard_024`) draw mostly on order counts
from `fact_web_order_header` rather than on these event tables. The event tables are
present for model breadth and for questions about how a funnel would be modelled here.
