---
kind: reference
title: Real estate and facilities dashboards
scope: dashboards
owner: facilities-analytics
domains: [real_estate]
covers:
  dashboards:
    - dashboard_020
    - dashboard_021
  visualizations:
    - viz_real_estate_*
---

# Real estate and facilities dashboards

## The two dashboards

- **`dashboard_020` — Real Estate & Facilities Costs.** Lease payment, utility cost,
  renovation cost, disposal cost and waste tons, by month, quarter and year.
- **`dashboard_021` — Energy & Maintenance Overview.** Renovation cost and disposal cost as
  repeated single-figure tiles, waste tons over time, and a paired waste-and-lease tile.

## Energy is in the model and barely on the dashboards

`dashboard_021` is titled for energy and maintenance. Energy consumption lives in
`fact_energy_consumption` with `maximum_total_kwh_consumed` as its pre-built metric, and
maintenance in `fact_maintenance_request` — neither appears on the two tiles this dashboard
devotes to renovation and disposal cost. The kWh figure does surface indirectly: "Cost
(Energy Consumption)" appears in a paired tile on the *sales* dashboard, because the
generator paired it there.

## Five cost streams, no total cost of occupancy

Lease payments, utility cost, renovation spend, waste disposal and maintenance are five
separate facts and there is no metric that adds them into a cost of occupancy. That total
is the obvious thing to want from these dashboards and it has to be defined; the components
are each available per property through `dim_property`.

## Costs are absolute, not per square metre

Every measure here is a currency total or a physical quantity, with no normalisation by
floor area or by store count. Comparing a flagship store's lease payment with a small
format's is comparing sizes, not efficiency. The normalised view is in the score tables —
`fact_re_attr_01` Lease Efficiency Score, `attr_02` Property Utilization Score, `attr_04`
Utility Cost Efficiency Score — none of which is displayed.

## Where the numbers come from

`fact_lease_payment`, `fact_utility_cost`, `fact_renovation_spend`, `fact_waste_disposal`,
`fact_energy_consumption`, `fact_maintenance_request`. Sliced by `dim_property`,
`dim_lease_type`, `dim_facilities_category`, `dim_utility_type`, `dim_maintenance_type` and
`dim_store_format`.
