---
kind: reference
title: Inventory and supply chain dashboards
scope: dashboards
owner: supply-chain-analytics
domains: [inventory]
covers:
  dashboards:
    - dashboard_006
    - dashboard_007
  visualizations:
    - viz_inventory_*
---

# Inventory and supply chain dashboards

## The two dashboards

- **`dashboard_006` — Inventory Health & Stock Levels.** Quantity, units on hand, inventory
  value, stock movement quantity, purchase-order count and amount, line amount and receipt
  quantity.
- **`dashboard_007` — Supply Chain & Purchase Orders.** The supplier scorecard measures —
  quality score, delivery score, cost score — plus current stock, days of cover and quantity
  by channel and region.

## Snapshots must not be summed

`fact_inventory_snapshot_daily` and `fact_aged_inventory` are snapshots: one row per item per
day. "Units on Hand by Quarter" is therefore a sum of ninety-odd daily snapshots, not the
stock held at quarter end, and it will be roughly ninety times any figure a warehouse
manager recognises. This is the workspace's clearest example of a metric that is
arithmetically correct and operationally wrong.

## Days of cover and current stock come from SQL

`viz_inventory_0171` (Current Stock) and `viz_inventory_0172` (Days of Cover) resolve through
`sql_inventory_health`, which applies its own as-of logic to pick the latest snapshot. Those
two tiles are therefore the ones to trust for a point-in-time stock question, and the reason
they disagree with the summed snapshot tiles beside them.

## The supplier scorecard is three separate scores

Quality, delivery and cost scores come from `fact_supplier_scorecard` as three columns. They
are not components of a single composite and no weighted overall score exists, so ranking
suppliers means choosing which dimension matters.

## Where the numbers come from

`fact_inventory_snapshot_daily`, `fact_aged_inventory`, `fact_stock_movement`,
`fact_transfer_order`, `fact_purchase_order_header`, `fact_purchase_order_line`,
`fact_goods_receipt`, `fact_supplier_scorecard`, plus `sql_inventory_health`. Sliced by
`dim_warehouse`, `dim_stock_location`, `dim_supplier`, `dim_inbound_carrier`,
`dim_lead_time_bucket` and `dim_reorder_status`.
