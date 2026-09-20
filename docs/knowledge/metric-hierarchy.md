---
keywords: [metric, hierarchy, naming]
strategy: AUTO
---

# GlobalMart metric conventions

## Metric layers

GlobalMart's metrics are layered, and the layer is in both the metric id and its tags, L1 through L5.

L1 metrics (`metric_l1_*`) are base aggregations over a single fact column. They are the only layer that touches a fact directly.

L2 metrics (`metric_l2_cross_*`) are ratios between two L1 metrics, such as order count over net revenue.

L3 metrics (`metric_l3_*`) apply a filter to an L1 or L2 metric, usually a WHERE on a dimension attribute such as channel type.

L4 and L5 metrics compose further on top of the lower layers.

Prefer the lowest layer that answers the question. Total net revenue is an L1 metric; net revenue for one channel is an existing L3 metric, not an L1 metric with a filter added.

## Choosing a revenue metric

Three metrics have "revenue" in the name and they are not interchangeable.

Use `metric_l1_total_net_revenue` by default. Net revenue is after returns and discounts.

`metric_l1_sql_margin_bridge_gross_revenue` is gross, before returns and discounts. It exists for the margin bridge and is the wrong figure elsewhere.

`metric_l1_sql_net_sales_summary_net_revenue` agrees with total net revenue but is scoped to its own SQL dataset's grain, so it does not slice by every dimension.

## Choosing a date dimension

GlobalMart has two date dimensions, and choosing the wrong one silently changes the answer.

Use `transaction_date` for operational questions: daily sales, footfall, stock movement. It is when the transaction happened.

Use `fiscal_date` for anything compared against a budget or reported by period, because the fiscal year does not start in January.

When a question says "last quarter" in a financial context it means a fiscal quarter, so group by `fiscal_date`.
