# FEAT-019 — C0 fit spike findings

**Date:** 2026-10-22 · **gdcloud:** `v0.51.0` (commit `8a293cf`, ecommerce's pin) · **Python:** 3.14.0

Tasks 1 and 3 were answered offline. Task 2 has an offline answer from gdcloud's source, and its
live round trip on a scratch dev workspace is still to run.

## D3 — `gooddata-sdk` version (task 1): resolved, no conflict

- gdcloud `v0.51.0` declares `gooddata-sdk>=1.72`, and GlobalMart pins `==1.75.0`. They resolve
  together to **1.75.0**, so GlobalMart keeps its exact pin.
- In a scratch copy of the repo with `requires-python = ">=3.14"` and the gdcloud git pin added,
  `uv lock` resolved 57 packages and `uv sync --all-extras --dev` installed cleanly.
- In the same environment, the existing suite passes: **789 passed, 2 skipped**. `ruff check src
  tests` and `mypy` are both clean, and the `globalmart`, `gd-agents` and `gd-ci` entry points all
  load.

**Finding for task 6:** hatchling refuses to build a package with a git-URL dependency unless
`pyproject.toml` sets this:

```toml
[tool.hatch.metadata]
allow-direct-references = true
```

Without it, `uv lock` succeeds but `uv sync` fails with "cannot be a direct reference".

## D4 — Python 3.14 (task 1): resolved, no fallout

The `data` and `agents` extras install and the full test suite passes on 3.14.0. The repo's own
`.venv` is already on 3.14. Only `requires-python`, mypy's `python_version` and CI's interpreter
need to change.

## D7 — labels and SQL dialect (task 3): resolved

- `gdcloud/dp_affected.py` (`dp_label`, `_build_label_map`) requires a label to be non-blank,
  uppercase, unique across the catalog and different from `TOOLING`. There is no character-class
  rule, so `GM_SALES`, `GM_STORE_OPS` and `GM_REAL_ESTATE` are all valid. PR labels are matched
  case-insensitively against the catalog (`dps_from_labels`).
- `gdcloud/init_project/discovery.py` maps `MOTHERDUCK` to sqlglot dialect **`duckdb`**, so
  `config.yml` gets `sql_dialect: duckdb`.

## D5 — AI content and WDFs through gdcloud (task 2): offline answer favorable, live check pending

From the `v0.51.0` source:

- **Upload** (`gdcloud/utils/workspace.py`) puts the LDM with `put_declarative_ldm`, then the
  analytics layer with `put_declarative_analytics_model`. The analytics layer is built from the
  **SDK's full `CatalogDeclarativeAnalytics` model**, not a hand-picked subset. Every class the SDK
  models therefore travels, including memory items, parameters, attribute hierarchies, dashboard
  extensions and export definitions. `data_product_export.py` maps all of these folders explicitly.
- **Memory items:** by default (`--memory-items true`) the committed items **replace** the
  workspace's own, which is the behavior GlobalMart wants: the repo is the truth. With
  `--memory-items false`, the workspace's existing items are kept instead.
- **Store** (`gdcloud/store_to_branch.py`) has the same `--memory-items` switch, plus a `--filters`
  switch that fetches WDFs into `workspace_data_filters.json`.
- **WDFs** (`gdcloud/utils/wdf.py`): if a DP has no `workspace_data_filters.json`, the upload is a
  successful no-op. GlobalMart's drop policy (no WDFs in any target) therefore needs no special
  handling. The projector simply emits no such file.

**Still to prove live (task 2):** that a `gd-upload` → `gd-store` round trip of the parent and
`globalmart_store_ops` on a scratch dev workspace gives an empty `diff -r`. That run would
surface any SDK-level loss or gdcloud canonicalization, such as tag normalization
(`normalize_analytics_empty_tags`) or YAML formatting. It writes to a live org, so it needs an
explicit go-ahead (STEERING § AI Behavior).

## Live run (task 2), 2026-10-22: blocked by the org's workspace plan limit

`gd-upload --environment dev --data-product-id globalmart globalmart_store_ops` against a scratch
gdcloud project (masters `globalmart_spike` and `globalmart_store_ops_spike`, both confirmed free
beforehand) failed on workspace creation for both DPs:

```
400 Bad Request — "Reached plan limits. Upgrade to create more workspaces."
```

Nothing was created. A re-list afterwards shows 25 workspaces and no `*spike*`. The
`petertomko.demo.cloud` org holds exactly 25 workspaces: 13 GlobalMart (the legacy `globalmart` +
`globalmart-<domain>`), 5 ecommerce, and 7 others. **25 is the plan's cap**, confirmed from the
org's own API: `GET /api/v1/entities/entitlements` returns `WorkspaceCount = 25` and
`Tier = DEMO`, and `GET /api/v1/actions/collectUsage` returns `WorkspaceCount = 25` (and
`AiWorkspaceCount = 13`). It is a plan entitlement, not a technical limit: raising it means
changing the org's DEMO-tier entitlement.

This affects more than the spike. The breakdown's ID scheme (D1) adds 13 new `<dp>_dev` plus 13
new `<dp>_test` workspaces on this org, which is 26 creates on an org that can't create one.
Ecommerce's FEAT-003 (`ecommerce_demo_test` + tenants) is hit by the same cap. The AI Usecases org
(preprod + prod = 26 more) has an unknown limit.

**Decision (user, 2026-10-22):** raise the workspace cap on the org, keeping D1 as designed.
Task 2 and every live task (48+) wait for the higher limit. Offline tasks (5–47, except GitHub
setup in task 42) can proceed in the meantime.

## Live run #2 (task 2, parent only), 2026-10-22: LDM reference cycle

After the domain cleanup (org at 13/25), `gd-upload` of the projected parent into scratch
workspace `globalmart_spike` created the workspace, then failed on the LDM upload:

```
400 — "Dataset references form a cycle: 'dim_employee' -> 'dim_department' -> 'dim_employee'"
```

- Across all 225 datasets there is **one** cycle: `dim_employee.department_id → dim_department`
  and `dim_department.manager_id → dim_employee`. It exists in the repo and in the live
  `globalmart` workspace.
- The legacy publish succeeds because it uses one whole-workspace `put_declarative_workspace` call,
  which accepts the cycle. gdcloud uploads the LDM on its own through `put_declarative_ldm`, and
  that endpoint validates for cycles.
- Nothing in `analytics_model/` references anything manager-related. The attribute
  `dim_department.manager_id` exists independently of the reference.
- Dropping the `dim_department → dim_employee` reference, and keeping the attribute, breaks the
  cycle and costs nothing visible.

`globalmart_spike` was deleted afterwards, leaving 13 workspaces on the org.

**Fix (user decision, 2026-10-22):** drop the `dim_department → dim_employee` reference and keep
the attribute. After that, `split` regenerated only `globalmart-hr.json`, every offline gate is
green, and 789 tests pass.

## Live run #3 (task 2, parent only), 2026-10-22: D5 confirmed, lossless

1. `gd-upload` into the scratch workspace `globalmart_spike` succeeded: workspace created, LDM
   uploaded, 14 AI memory items deployed, analytics model uploaded, in 9.7 s.
2. `gd-store` pulled the workspace back into the scratch project.
3. The stored tree was compared with the uploaded projection, YAML parsed on both sides.

| Result | Files |
|---|---|
| Identical content, different YAML formatting (gdcloud's style) | 1766 |
| Real differences: `memory_items/*.yaml`, `keywords` list **order only** (same set, server order) | 14 |
| Added by `gd-store`: `workspace_data_filters.json` = `{"data": []}` | 1 |
| Lost | 0 |

**D5 is resolved.** Memory items, parameters, attribute hierarchies, dashboard extensions and
export definitions all survive the round trip. The projector (C4) should:

- emit gdcloud's YAML formatting (run gd-format-yaml, or match its style)
- emit an empty `workspace_data_filters.json`
- treat memory-item `keywords` as unordered in the equivalence proof

`globalmart_spike` was deleted afterwards. The org then held 14 of 25 workspaces, because
ecommerce's `ecommerce_demo_test` ("Ecommerce Demo (TEST)") was created by other work in the
meantime.

## Net effect on the breakdown

- D3, D4 and D7 are closed with no change to the design.
- D5 is not a stop signal on the offline evidence. Expect the live run to surface formatting
  differences only, which C4 absorbs. That is the planned "fold canonicalization back into C4"
  loop.
- Task 6 gains one line: `allow-direct-references`.
