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
status: done
tags: []
updated: '2026-10-24'
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

## Outcome — 2026-09-23 (partial — not closed as done)

**The defect this feature existed for is fixed and proven live.** Dashboard date filters did
nothing because every `dateFilter` in the layout was missing the `dataSet` that says *which*
date it filters on. All 32 dashboards are now bound, the derivation is per dashboard rather
than blanket, and the binding is checked in CI.

Proven against `demo-cloud` by executing the same visualization under three windows and an
out-of-range one: **960 / 262 / 168 / empty**. Before the fix, every window returned the same
number.

### Met

- **AC 1** — every filter context carrying a `dateFilter` now carries a `dataSet` that exists
  in that workspace's LDM.
- **AC 2** — derived per dashboard by walking visualizations → metrics → facts → date
  references. All 32 resolve to `transaction_date`; `globalmart-store-ops` carries both
  `fiscal_date` and `transaction_date`, so the walk rather than a substitution is what makes
  that workspace correct.
- **AC 3** — derivation fails loudly, naming the dashboard, on zero or ambiguous resolution.
- **AC 4** — FEAT-013 landed, so the shipped `-11..0` month windows cover real rows:
  174,372 rows spanning 2024-09-21 → 2026-09-20.
- **AC 6, partially** — `globalmart datefilters bind --check` runs in CI, so a dashboard added
  without a bound filter fails the build. This covers the *binding*, not the behaviour.

### NOT MET

- **AC 5 — the regression gate does not exist.** The committed tests
  (`tests/test_datefilters.py`) are structural: they assert every filter is bound, that each
  dashboard resolves to exactly one date instance, that dates are reached through metrics, that
  binding is idempotent and that an override wins. **None of them executes a visualization
  under two windows and asserts the results differ.** That gate is the thing that would catch
  this defect coming back, and it is precisely what the live investigation did by hand.
- **AC 6, the rest** — with no AC-5 gate there is nothing to run across the parent and the 12
  domain workspaces.
- **AC 7 — `fact_aged_inventory` and `fact_purchase_order_line` are still undecided.** No date
  column, no allowlist entry, no recorded reason. The spec said they must not be left
  undecided, and they are.
- **AC 8 — unverified.** The hand-patch applied to
  `globalmart-ecommerce`/`filter_context_002` during the investigation was presumably
  superseded by the subsequent publish, but nothing checked, and "presumably" is not the
  standard this criterion set.

### Why this is left open rather than closed

Three of eight criteria are unmet and they are not cosmetic: together they are the difference
between *fixed* and *fixed and protected*. A structural test proves the layout is well-formed;
only a two-window execution proves the filter does anything. Closing this as done would record
that the regression gate exists, and someone would later rely on it.

The honest state is: the bug is fixed, the fix is proven by hand against live data, and the
gate that would keep it fixed has not been built.

### Follow-ups

- Build the AC-5 two-window gate and wire it across all 13 workspaces (AC 6).
- Decide `fact_aged_inventory` and `fact_purchase_order_line`: a date column from the
  generator, or a named allowlist with the reason they are snapshots (AC 7).
- Confirm no workspace still carries the investigation hand-patch (AC 8).

## Outcome — 2026-10-24

The three open criteria are met and AC 8 is now checked. All eight acceptance criteria hold.
Two criteria were read against how the repo works today rather than as first written. AC 6's
"parent and all 12 domain workspaces" now means: every deployed gdcloud environment, plus any
workspace on demand. Since ADR 011 the repo releases one data product through gdcloud, and the
12 domain workspaces are local-only.

### AC 5 — met: the live two-window gate

`globalmart datefilters gate --target <profile> [--workspace-id <id> ...] [--verbose]`
(`src/globalmart/datefilter_gate.py`). It is read-only, so it takes no `--apply`. For every
dashboard whose live filter context carries a `dateFilter`, it does the following:

- It reads the binding from the **live** filter context: the dataset and the relative window
  (`-11..0` months as shipped). The same window length immediately before it (`-23..-12`) is
  the comparison window.
- It picks one visualization **whose content reaches the bound date**. This uses the same LDM
  walk that `datefilters bind` derives from, now shared as `datefilters.DateReach`. It runs
  that visualization's metrics as totals (one row) under both windows. The visualization's own
  attribute filters are kept. Its own date filter on the same dataset is replaced, as the UI
  does.
- **Fails** when the recent window is empty (stale data), when both windows return identical
  numbers (the filter binds to nothing), on an execution error, when the filter is unbound, or
  when no tile can reach the date. **Passes** only when the numbers differ and the recent one
  is non-empty. A workspace that cannot be read, or that has nothing to gate, also fails. Every
  failure names the workspace, the dashboard, each tried visualization and its two numbers.
- Cost is bounded: at most `--max-candidates` (default 3) visualizations per dashboard, and the
  first pass stops. In practice that is 2 executions per dashboard, about 15 s for 32 dashboards.

The snapshot-tile skip came from a real finding on the first live run. `dashboard_017` *Customer
Feedback & NPS* leads with three tiles on `sql_customer_ltv_snapshot` / `sql_rfm_segments`.
These return the same number under every window (1.06984e9 / 2.99505e8 / 50000), because no
date can reach them. Blaming them would be a false failure. Choosing them blindly would hide a
genuinely dead dashboard. The gate selects by LDM reach, and a dashboard with no date-reaching
tile fails as `NO_DATED_VISUALIZATION`.

The decision logic is unit-tested against behaving fakes in `tests/test_datefilter_gate.py` (22
tests). The cases covered: pass, same, stale, all-empty, error, unbound live filter, a snapshot
tile skipped, a dashboard with no dated tile, candidate bound, retry on 503 but not on 400, an
unreadable workspace, a workspace with nothing to gate, and filter construction in
`measure_window`.

### AC 6 — met (as adapted)

- **CI, post-deploy:** a new `datefilters` job in `.github/workflows/globalmart_post_deploy.yml`
  is the project-owned workflow and not gdcloud-generated. It runs after every successful deploy
  by workflow 3, 4 or 5, against the environment and master that `globalmart gdcloud scope`
  reads back from the deploy tag. It uses the same `gdcloud-<env>` profile, `TOKEN_GOODDATA`
  secret and GitHub Environment as the knowledge publish. It is a separate job, so a corpus
  failure and a date-filter failure cannot mask each other.
  `tests/test_release_wiring.py::test_post_deploy_gates_date_filters_on_the_deployed_master`
  pins the wiring.
- **On demand:** any profile and any workspace, domains included, through `--workspace-id`.
- The offline `datefilters bind --check` in `ci.yml` still guards the binding at PR time.

Live results, 2026-10-24, all exit 0:

| Target | Workspace | Dashboards gated | Pass |
|---|---|---|---|
| gdcloud-dev | `globalmart_dev` | 32 | 32 |
| gdcloud-test | `globalmart_test` | 32 | 32 |
| gdcloud-preprod | `globalmart_preprod` | 32 | 32 |
| gdcloud-prod | `globalmart_master` | 32 | 32 |
| demo-cloud | `globalmart` (legacy parent) | 32 | 32 |
| usecases-ai | `globalmart-customer` | 3 | 3 |
| usecases-ai | `globalmart-marketing` | 3 | 3 |
| usecases-ai | `globalmart-store-ops` | 3 | 3 |
| usecases-ai | `globalmart-ecommerce` | 2 | 2 |

Sample numbers from `globalmart_dev` (recent vs earlier): `dashboard_000` 42,454 vs 39,641;
`dashboard_001` 4.35M vs 5.04M; `dashboard_012` 1.45M vs 1.07M; `dashboard_017` 26,542 vs
25,229. Run `--verbose` to see every dashboard. As a negative check, a workspace that is not
deployed (`globalmart-sales` on usecases-ai) exits 1 as UNREADABLE.

### AC 7 — met: both facts decided

- **`fact_aged_inventory` is allowlisted** in `datefilters.UNDATED_FACTS`, with the reason that
  it is a point-in-time snapshot of stock by age. `age_days` is its time axis, and no event date
  exists (`aged_id, product_id, store_id, age_days, quantity`).
- **`fact_purchase_order_line` is not dateless, and so is not allowlisted.** It has no date
  column of its own. But it references `fact_purchase_order_header` via `po_id`, and the
  header's `po_date` maps to `transaction_date`, so a date filter reaches PO lines through the
  header. The answer to the open question is that the generator was right not to emit a line
  date.
- **Enforced:** `datefilters.undecided_facts()` walks references transitively and flags two
  things: any `fact_*` dataset that reaches no date and is not allowlisted, and any allowlist
  entry that has gone stale (now dated, or gone). The result is part of `bind_date_filters`'
  report, so `datefilters bind --check` in CI fails on a new undecided fact. Against today's
  layout it is empty. With an empty allowlist it flags exactly `fact_aged_inventory`. Tests are
  in `tests/test_datefilters.py`.

### AC 8 — met: no workspace carries the hand-patch

A read-only scan on 2026-10-24 covered every `globalmart*` workspace on both orgs. On demo.cloud
those are `globalmart`, `globalmart_dev` and `globalmart_test`. On usecases-ai they are
`globalmart_preprod`, `globalmart_master` and the four domains. Every `dateFilter` in every
filter context is the shipped relative `-11..0` `GDC.time.month` bound to `transaction_date`.
There is no absolute filter anywhere. `globalmart-ecommerce` no longer exists on demo.cloud,
where the patch was applied. On usecases-ai its `filter_context_002` matches the committed
layout. The gate keeps this checked: any live date filter that is not relative is printed as a
`NOTE` against its dashboard.

### Files

- `src/globalmart/datefilter_gate.py` (new): the gate.
- `src/globalmart/datefilters.py`: `DateReach` extracted with no behaviour change, plus
  `UNDATED_FACTS`, `undecided_facts` and `BindReport.undecided_facts`.
- `src/globalmart/cli.py`: `datefilters gate`.
- `.github/workflows/globalmart_post_deploy.yml`: the `datefilters` job.
- `tests/test_datefilter_gate.py` (new), `tests/test_datefilters.py`,
  `tests/test_release_wiring.py`.

Gate run on this change: `pytest` (925 passed, 2 skipped), `ruff check`, `ruff format --check`,
`mypy src` and `yamllint .`, all clean.
