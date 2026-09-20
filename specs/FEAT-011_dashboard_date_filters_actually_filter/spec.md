---
abandoned_at: null
abandoned_reason: null
appetite: s
blocked_at: null
blocked_by: null
confidence: high
created: '2026-09-20'
cycle: null
depends_on:
- feat-001
- feat-002
- feat-004
- feat-006
- feat-013
enables:
- feat-009
goal: goal-01
id: feat-011
name: 'Dashboard date filters actually filter: bind every filter context to its date
  dataset, bring the data window to the present, and gate the regression'
sources: []
status: draft
tags: []
updated: '2026-09-20'
---

## Summary

Every GlobalMart dashboard ships a date filter that does nothing. Changing it does not change a
single number, in the parent or in any of the 12 domain workspaces. This was found by hand on
2026-09-20 and then reproduced against the live org.

There are two independent defects, and they hide each other. Fixing either one alone makes the
dashboards look *worse*, which is probably why this survived a full verification pass.

### Evidence — reproduced live against demo-cloud, 2026-09-20

All 32 filter contexts in `layouts/workspaces/globalmart/analytics_model/filter_contexts/` carry a
date filter. **None of them carries a `dataSet`.**

```yaml
- dateFilter:
    from: '-11'
    granularity: GDC.time.month
    to: '0'
    type: relative
```

`dataSet` is a real, optional property of `DashboardDateFilterDateFilter` (typed `IdentifierRef` in
the API client). Omitting it makes the filter a *common* date filter, which resolves against
whatever date dataset each insight declares — and no insight in the tree declares one
(`dateDataSet` appears zero times). So the filter binds to nothing and is silently ignored.

**Defect 1 — nothing to bind to.** The dashboard renders the unfiltered result no matter what the
user selects. This is the reported symptom.

**Defect 2 — the window is outside the data.** `-11..0` months resolves to Oct 2025 → Sep 2026.
The fact tables span **2023-01-01 → 2024-12-28**, roughly 21 months stale. So the moment defect 1
is fixed, every dashboard goes blank instead of wrong.

Proof, via `metric_l3_0000_0` (*Order Count — In-Store Channel*) on `globalmart-ecommerce` through
the AFM execution API:

| Filter on `transaction_date` | Result |
|---|---|
| none | 960 |
| 2023-01-01 .. 2023-06-30 | 262 |
| 2024-01-01 .. 2024-06-30 | 168 |
| 2025-01-01 .. 2025-06-30 | *(empty)* |

The data filters correctly. Only the dashboard wiring and the window are wrong.

Confirmed fix, applied live to `globalmart-ecommerce` / `filter_context_002` and accepted with
HTTP 200:

```yaml
- dateFilter:
    dataSet:
      identifier:
        id: transaction_date
        type: dataset
    from: '2024-01-01'
    granularity: GDC.time.date
    to: '2024-06-30'
    type: absolute
```

Ruled out along the way: no widget sets `ignoreDashboardFilters` (all 24 in ecommerce are empty
lists), and `fact_web_order_header` does correctly reference `transaction_date`. The LDM is sound
wherever a date exists.

### Why the existing gates missed it

FEAT-006 executes every visualization and asserts it returns without error. An unfiltered
visualization returns without error. Nothing in the harness has ever asserted that a filter
*changes* anything, so a filter that does nothing is indistinguishable from a filter that works.
That gap is the durable part of this feature; the two fixes are a day's work, the gate is what
stops it coming back.

## Appetite

`s` — 1–3 days. The binding is mechanical once derived, and the gate reuses FEAT-006's execution
machinery. The data window is FEAT-013's cost, not this feature's. If it grows past three days it is because the
date-dataset derivation turned out to be ambiguous, which is the one genuine unknown.

## Acceptance Criteria

1. Every filter context in the layout tree that contains a `dateFilter` also contains a `dataSet`
   identifying a date instance that exists in that workspace's LDM.
2. The date dataset is **derived per dashboard**, not hardcoded: walk the dashboard's
   visualizations → metrics → facts → date references and select the date instance that dashboard's
   own content uses. `globalmart-store-ops` carries both `fiscal_date` and `transaction_date`, so a
   blanket substitution is wrong by construction.
3. Derivation fails loudly. A dashboard whose content resolves to zero date instances, or to more
   than one with no tiebreak, stops the build with the dashboard id named. It is never guessed and
   never silently skipped.
4. The gate is run against data whose window reaches the present (delivered by FEAT-013), so the
   shipped relative windows (`-11..0` months) cover real rows. Until FEAT-013 lands, the gate is
   expected to fail — honestly, and for the right reason.
5. A regression gate asserts, per dashboard, that two different date windows produce **different**
   results — with at least one window non-empty. A filter that returns empty for every window fails,
   and so does one that returns the same number for every window.
6. The gate runs against the parent and all 12 domain workspaces, and is wired into the same CI path
   as the existing checks.
7. `fact_aged_inventory` and `fact_purchase_order_line` are resolved explicitly — either given a date
   column by FEAT-013, or recorded in a named allowlist with the reason they are snapshots.
   They are not left undecided.
8. The live hand-patch applied to `globalmart-ecommerce`/`filter_context_002` during investigation is
   either superseded by a proper publish or reverted, so no workspace is left carrying a manual edit.

## Scope

- A derivation step that computes, per dashboard, which date instance its content depends on, and
  writes `dataSet` into that dashboard's filter context in the parent layout. This is transitive
  closure over the same graph FEAT-004 already walks for domain membership — reuse it, do not write
  a second traversal.
- A date-effect check in the verification harness (FEAT-006), run per dashboard, comparing two
  windows.
- Re-split and republish so the 12 domain workspaces inherit the corrected filter contexts.
- A decision, and its implementation, for the two dateless fact tables.

## Out of Scope

- **Attribute filters.** The same filter contexts carry attribute filters on
  `dim_store.region_id`, `dim_currency.currency_code` and others. They may or may not work. This
  feature fixes dates; whether attribute filters bite is a separate question, and probably a
  separate finding.
- **Workspace data filters.** FEAT-012 territory. Related only in that both are filters that can
  silently do nothing — the gate built here is the pattern that feature should copy.
- **Changing the data at all.** FEAT-013 owns the archive transform that moves the window. This
  feature consumes the result; it does not regenerate, reshape or rescale anything.
- Redesigning the dashboards' default filter selections. The shipped `-11..0` relative window is
  kept; only its binding and the data behind it change.
- Making dashboards respond to filters they were never wired to (e.g. widgets built purely on
  dimension tables). Out of scope, but worth surfacing if the gate finds them.

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Date-dataset derivation is ambiguous for some dashboards — content touches both `fiscal_date` and `transaction_date` | Medium | Medium | Fail loudly with the dashboard named (AC 3) and resolve the handful by hand in an explicit override map, rather than picking a default that is quietly wrong half the time |
| Data goes stale again in a year and this recurs | High | Medium | The gate (AC 5) fails as soon as every window returns empty, so staleness becomes a CI failure rather than a discovery in front of a customer |
| The effect gate is flaky — two windows legitimately return the same number for a sparse metric | Medium | Medium | Choose windows from the actual data range, require one non-empty result, and allow a per-dashboard override with a stated reason rather than weakening the assertion globally |
| Fixing the binding without the data window ships blank dashboards | High if done out of order | High | FEAT-013 lands **first**. If it slips, this feature still ships the binding and the gate, and the gate fails honestly until the data moves |

## Dependencies

- **Depends on:** feat-001 (the layout tree that holds the filter contexts), feat-002 (publishing the
  corrected tree), feat-004 (the transitive-closure traversal the derivation reuses, and the split
  that propagates the fix to 12 workspaces), feat-006 (the execution harness the gate extends),
  feat-013 (the archive transform that moves the data window).
- **Enables:** feat-009 — the A2A orchestrator demo answers questions over these workspaces. A
  question like "which channel had the worse month" against data that stops in 2024, through filters
  that do not filter, produces a confidently wrong answer in front of a customer.

## Related Research

- `DashboardDateFilterDateFilter` in `gooddata_api_client` declares `data_set: (IdentifierRef,)` as
  an optional property. `IdentifierRef` is `{identifier: {id, type}}`. Verified 2026-09-20.
- Live read of `globalmart-ecommerce` filter contexts confirms the published org matches the
  committed layout — no drift, the defect is in the source of truth.
- Column survey across all 215 tables: no column appears in more than 40 of them. `customer_id` 40,
  `store_id` 39, `product_id` 32, `country_id` 8, `region_id` 5. Relevant here only as context for
  which facts can carry a date.
- Fact datasets lacking any date reference: `fact_aged_inventory` and `fact_purchase_order_line`
  (2 of 18 facts in `globalmart-sales`, 1 of 8 in `globalmart-inventory`; every other workspace is
  clean). `fact_aged_inventory` is `aged_id, product_id, store_id, age_days, quantity` — genuinely
  dateless.
- Date instances in the parent LDM: `transaction_date` and `fiscal_date`. Per-workspace after the
  split: most carry `transaction_date` only; `globalmart-store-ops` carries both.

## Open Questions

- Should the shipped default filter stay relative (`-11..0` months, needs periodically fresh data)
  or become absolute (pinned to the data range, always correct, looks frozen in a demo)? Relative
  plus the staleness gate is the better pairing, but it means accepting a recurring regeneration.
- What end date? Literally today at generation time, or the start of the current month for a tidier
  boundary? The latter is easier to reason about when reading a dashboard.
- Should the date-effect gate live in FEAT-006's harness or as its own check? Folding it in gets CI
  wiring free but grows a module that is already doing four things.
- Do attribute filters on these same dashboards actually work? Worth ten minutes of the same
  technique before this feature closes — if they are broken too, the scope judgement changes.
- Is `fact_purchase_order_line` genuinely dateless, or is it missing an `order_date` the generator
  should have emitted? Unlike aged inventory, a PO line has a natural date.
