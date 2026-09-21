---
kind: reference
title: Marketing dashboards
scope: dashboards
owner: marketing-analytics
domains: [marketing]
covers:
  dashboards:
    - dashboard_008
    - dashboard_009
    - dashboard_029
  visualizations:
    - viz_marketing_*
---

# Marketing dashboards

## The three dashboards

- **`dashboard_008` — Marketing Campaign ROI.** Campaign spend, spend count, email send,
  open and click counts, display impression count, paid-search click cost and total spend.
- **`dashboard_009` — Email & Digital Campaign Analytics.** Spend count by channel and
  region, send count, open count over time, and a paired open-versus-click tile.
- **`dashboard_029` — Campaign Attribution & Media Mix.** Impression count, click cost and
  spend across month, quarter and year.

## The email funnel is three tables and no rate

`fact_email_send`, `fact_email_open` and `fact_email_click` are separate facts with their own
counts. No open rate or click-through rate metric exists, so those are ratios the asker
defines — and because each table is generated independently, nothing guarantees that clicks
are a subset of opens or opens a subset of sends.

## ROI is named on a dashboard that shows spend

`dashboard_008` is titled for ROI and its tiles are spend and engagement counts; the return
side is in `sql_campaign_roi`, which no tile on it displays. Attribution is the same story on
`dashboard_029`: `sql_channel_attribution` holds the attribution logic and the tiles show
impressions, click cost and spend.

## Two impression sources

`fact_display_impression` and `fact_social_impression` both count impressions, on different
channels, and the tiles labelled simply "Impression Count" resolve to the display table.
Adding the two is legitimate only if the question is about total paid impressions across
both.

## Where the numbers come from

`fact_campaign_spend_daily`, `fact_email_send`, `fact_email_open`, `fact_email_click`,
`fact_display_impression`, `fact_social_impression`, `fact_paid_search_click`, plus
`sql_campaign_roi` and `sql_channel_attribution`. Sliced by `dim_campaign`, `dim_creative`,
`dim_ad_network`, `dim_audience_segment`, `dim_utm_source` and `dim_promotion`.
