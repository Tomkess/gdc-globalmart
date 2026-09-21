---
kind: reference
title: Loyalty dashboards
scope: dashboards
owner: loyalty-analytics
domains: [loyalty]
covers:
  dashboards:
    - dashboard_005
    - dashboard_016
  visualizations:
    - viz_loyalty_*
---

# Loyalty dashboards

## The two dashboards

- **`dashboard_005` — Customer Loyalty & Retention.** Attributed revenue, enrollment count,
  referral count, referral bonus, bonus points, bonus cost, points used and partner
  discount.
- **`dashboard_016` — Loyalty Program ROI.** Attributed revenue for the North region,
  enrollment count as three separate tiles, referral count over time, and a paired
  referral-bonus tile.

## Points earned, redeemed and expired are three tables

`fact_loyalty_points_earned`, `fact_loyalty_points_redeemed` and `fact_loyalty_expiry` are
separate facts, and there is no derived points-balance metric anywhere in the workspace. A
balance question needs earned minus redeemed minus expired, defined by the asker; the tiles
show the three flows and never the stock.

## Redemption happens in two places

`fact_loyalty_points_redeemed` records the redemption and
`fact_loyalty_redemption_at_pos` records the discount given at the till. The second is the
one the sales dashboards reach into — "Discount Amount (Loyalty Redemption at POS)" appears
in paired tiles across several domains — so loyalty discount shows up in sales figures
through that table rather than through points redeemed.

## Attributed revenue is a programme claim

`sql_loyalty_roi` computes attributed revenue, which is revenue the programme claims credit
for. It is an attribution model's output, not a measured quantity, and it will not reconcile
against net revenue because it is a share of it computed by rules inside the SQL statement.

## Where the numbers come from

`fact_loyalty_enrollment`, `fact_loyalty_points_earned`, `fact_loyalty_points_redeemed`,
`fact_loyalty_expiry`, `fact_loyalty_redemption_at_pos`, `fact_bonus_event`,
`fact_referral`, `fact_partner_redemption`, `fact_tier_change`, plus `sql_loyalty_roi`.
Sliced by `dim_loyalty_tier`, `dim_loyalty_campaign`, `dim_reward_type`, `dim_partner`,
`dim_bonus_type` and `dim_referral_source`.
