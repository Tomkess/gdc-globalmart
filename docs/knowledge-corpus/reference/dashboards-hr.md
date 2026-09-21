---
kind: reference
title: HR dashboards
scope: dashboards
owner: people-analytics
domains: [hr]
covers:
  dashboards:
    - dashboard_014
    - dashboard_015
    - dashboard_030
  visualizations:
    - viz_hr_*
---

# HR dashboards

## The three dashboards

- **`dashboard_014` — Employee Performance & Headcount.** Hours worked, gross pay,
  deductions, absence hours, training cost, headcount, active count and recruitment count.
- **`dashboard_015` — Payroll & Absence Analytics.** Gross pay and deductions as repeated
  single-figure tiles, plus absence hours over time.
- **`dashboard_030` — Workforce Productivity Index.** Headcount, active count and
  recruitment count across month, quarter and year.

## Headcount is a snapshot, and every metric over it is a sum

`fact_headcount_snapshot` holds one row per period per entity, and
`metric_l1_fact_headcount_snapshot_total_headcount` sums it. "Headcount by Year" is
therefore twelve monthly snapshots added together, which is not a headcount. The two
metrics that treat it correctly are hand-named: `minimum_total_headcount` and
`minimum_weekly_total_headcount`, the latter being the lowest weekly headcount across the
window.

## Repeated tiles are not a rendering fault

`dashboard_015` shows Gross Pay three times and Deductions three times. Those are genuinely
distinct visualization objects (`viz_hr_0300` to `0305`) that differ in filter or grain
while sharing a title, which is how the generator produces them. Two tiles with the same
title on this workspace are usually two different slices, and the only way to tell them
apart is to open them.

## Performance and retention are scores, not tiles

`fact_hr_attr_00` Employee Performance Score, `attr_01` Employee Retention Risk, `attr_02`
Training Effectiveness Score, `attr_03` Workforce Productivity Index and `attr_04` Employee
Attendance Score exist in the model. `dashboard_030` is named after the third of those and
displays headcount counts instead.

## Where the numbers come from

`fact_employee_hours`, `fact_payroll_transaction`, `fact_absence`,
`fact_headcount_snapshot`, `fact_recruitment`, `fact_training_completion`. Sliced by
`dim_employee`, `dim_department`, `dim_job_role`, `dim_contract_type`, `dim_shift_type`,
`dim_absence_reason` and `dim_training_type`. Note that payroll figures are personal data in
a real deployment; here the rows are synthetic and carry no real person.
