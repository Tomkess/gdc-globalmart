---
kind: reference
title: Risk and compliance dashboards
scope: dashboards
owner: risk-analytics
domains: [risk]
covers:
  dashboards:
    - dashboard_018
    - dashboard_019
    - dashboard_031
  visualizations:
    - viz_risk_*
---

# Risk and compliance dashboards

## The three dashboards

- **`dashboard_018` — Fraud Risk & Compliance.** Attribute value, fraud alert count and
  value, chargeback count and amount, and audit finding count.
- **`dashboard_019` — Audit Findings & Risk.** Alert value and chargeback count as repeated
  tiles, plus chargeback amount over time.
- **`dashboard_031` — Compliance & Cost Center Benchmarks.** The same measure set as
  `dashboard_018`, at different grains.

## "Attribute Value" is the score tables surfacing

Several tiles are titled "Attribute Value", which is the generic column name in the risk
score tables `fact_risk_attr_00` (Fraud Risk Score) and `fact_risk_attr_01` (Compliance
Adherence Score). The tile title says nothing about which score it is, so these are tiles
where the underlying metric has to be opened to interpret the number.

## Alerts and chargebacks are not the same event

`fact_fraud_alert` is a detection — something was flagged — and `fact_chargeback` is a
financial outcome, a payment reversed. A flagged transaction may never become a chargeback
and a chargeback may never have been flagged, so alert count and chargeback count are
independent series. A "fraud rate" comparing them is a comparison of two populations and
needs saying so.

## The three chargeback maxima

`maximum_total_chargeback_amount`, `maximum_total_chargeback_amount_from_total_metric` and
`custom_max_total_chargeback` all take a maximum over chargeback amount — the first over the
fact column, the other two over the level-1 metric. They are evaluation fixtures rather than
three intended measures; see *Duplicate and evaluation metrics*.

## Where the numbers come from

`fact_fraud_alert`, `fact_chargeback`, `fact_audit_finding`, `fact_risk_attr_00`,
`fact_risk_attr_01`. Sliced by `dim_fraud_type`, `dim_risk_category`, `dim_audit_type`,
`dim_compliance_framework`, `dim_cost_center` and `dim_payment_method`.
