---
kind: reference
title: Dimension tables
scope: data-model
owner: analytics-eng
covers:
  datasets:
    - dim_*
---

# Dimension tables

## What you can slice by

There are 68 `dim_*` datasets. The ones that appear in most questions are `dim_store`,
`dim_product`, `dim_customer`, `dim_channel_master` (Sales Channel), `dim_geography_region`,
`dim_geography_city`, `dim_geography_country`, `dim_employee`, `dim_supplier`, `dim_campaign`
and `dim_cost_center`.

## The hierarchies that exist

Geography is three separate datasets — country, region, city — rather than one dataset with
three levels, so a drill path across them is a join path and not a single attribute
hierarchy. Product category is two levels, `dim_category_l1` and `dim_category_l2`, with the
same caveat. `dim_fiscal_period` carries the fiscal calendar as a dimension, separate from
the `fiscal_date` date instance.

## The values that filters rely on

Two label values are used repeatedly by the generated level-3 metrics, and they are worth
knowing verbatim: `dim_channel_master.channel_type` takes the values *In-Store* and
*Online*, and `dim_geography_region.region_name` includes *North*. The 366 level-3 metrics
are filtered on exactly these, so a metric named "— Online Channel" is filtered on
`channel_type IN ("Online")` and on nothing else.

## Conformed and local dimensions

`dim_store`, `dim_product`, `dim_customer`, `dim_channel_master` and the geography set are
conformed: several fact tables reference each of them, which is what makes a figure
comparable across subject areas. The rest are local to one or two facts —
`dim_absence_reason` belongs to absence, `dim_return_reason` to returns,
`dim_shrinkage_category` to shrinkage events — and slicing an unrelated fact by one of them
is not possible rather than merely unhelpful.
