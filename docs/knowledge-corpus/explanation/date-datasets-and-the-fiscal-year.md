---
kind: explanation
title: Date datasets and the fiscal year
scope: data-model
owner: analytics-eng
anchor: true
covers:
  datasets:
    - transaction_date
    - fiscal_date
---

# Date datasets and the fiscal year

## Two date instances, one in use

The model carries two: `transaction_date` and `fiscal_date`. Every dashboard date filter and
every period-over-period metric is bound to **`transaction_date`**. As of 2026-09-21,
`fiscal_date` is referenced by no dashboard content and by no metric — it exists in the
model and nothing uses it.

That is recorded here rather than tidied away, because the alternative is someone spending
an afternoon working out why a fiscal filter has no effect. If a fiscal view is wanted, it
has to be built; it is not sitting there waiting to be switched on.

## The fiscal year starts in February

GlobalMart's fiscal year begins in February, so fiscal Q1 is February to April. A calendar
quarter comparison against a fiscal figure is off by one month at both ends, and the error
is small enough to look like a rounding difference rather than a structural one. Anything
labelled "quarter" in this workspace means a **calendar** quarter unless it came from
`dim_fiscal_period`.

## Why the date filters had to be bound explicitly

A dashboard date filter with no `dataSet` is inert: it renders, it accepts a range, and it
changes nothing. All 32 dashboards were in that state until the filters were bound to
`transaction_date` through the objects each dashboard actually references — its
visualizations, their metrics, and the metrics those metrics reference in MAQL. The binding
is enforced in CI, so a new dashboard cannot ship with a filter that silently does nothing.

## Period-over-period depends on this

The 400 level-4 metrics compute their comparison with `FOR PREVIOUS ({label/transaction_date.month})`
or the year equivalent. They are therefore always calendar month-over-month or
year-over-year on the transaction date, regardless of which date filter a dashboard offers,
and they cannot be re-pointed at a fiscal calendar by changing a filter.
