# 011 — GlobalMart is released by gdcloud, as one data product

**Status:** Accepted (2026-10-22); Stage B taken (2026-10-24)
**Date:** 2026-10-22, amended 2026-10-24
**Context:** FEAT-019; `config.yml`, `gd_data_product/`, `gd_plugin/`, `gdcloud_*.py`,
`config/targets.yaml`. Aligns with gd-ecommerce-demo's ADR 001 (gdcloud, four environments on two
orgs) and ADR 002 (a separate org repo owns org-level objects). **Revises** how ADR 001 and ADR
006's domain workspaces reach an org; it does not change how they are derived.

## Decision

GlobalMart's workspace content is released with **gd-cloud-tooling (`gdcloud`)**, pinned at
`v0.51.0`. That is the same toolkit and pin gd-ecommerce-demo uses on the same two orgs, so both
demo repos run one release process.

- **One data product, `globalmart`** (label `GM`): the parent workspace. It is released
  dev → test → preprod → prod, each environment to its own master on a shared org:

  | Env | Org | Master | Title |
  |---|---|---|---|
  | dev | `petertomko.demo.cloud` | `globalmart_dev` | GlobalMart (DEV) |
  | test | `petertomko.demo.cloud` | `globalmart_test` | GlobalMart (TEST) |
  | preprod | `usecases-ai.demo.cloud` | `globalmart_preprod` | GlobalMart (PREPROD) |
  | prod | `usecases-ai.demo.cloud` | `globalmart_master` | GlobalMart |

- **The 12 domain workspaces are local-only.** `domains.yaml`, `generated/workspaces/*.json` and
  the `split --check` / `domains validate --strict` gates stay. `globalmart publish domains
  --target <t> --apply` redeploys the domains on demand, and no gdcloud workflow ever creates
  one. The live copies on demo.cloud were backed up (`backups/demo-cloud/<id>/20261022T1205*Z/`)
  and deleted on 2026-10-22.
- **Stage A (2026-10-22 → 2026-10-24, superseded): the layout stayed the source.**
  `layouts/workspaces/globalmart/` (placeholder form, ADR 001) was where changes were made, and
  `gd_data_product/globalmart/` was *derived* from it by `globalmart gdcloud project`, gated by
  `--check` in `ci.yml` and by the `projection_current` gd-ci check.
- **Stage B (2026-10-24): `gd_data_product/globalmart/` is the only authoring tree.** See
  [Stage B](#stage-b-2026-10-24) below.
- **A data source of its own.** `gdc_ds_globalmart_motherduck` on both orgs (ecommerce ADR 002
  naming). It reads the same MotherDuck schema the legacy `globalmart-motherduck` reads.
- **No org-level release from this repo.** `automation.org_release` and `organization_snapshot` are
  off. The `org_scope` gd-ci check fails if either is turned on, or if a `gd_organization*/` tree
  appears.
- **gdcloud has no concept of the project-owned steps, so they run around it.** These are the data
  freshness gate (`data ensure --check` before merge) and the knowledge corpus publish (after a
  successful deploy, into that environment's master only). The order data → workspace → knowledge
  (FEAT-018) therefore holds structurally.
- The legacy `globalmart` workspace and the `demo-cloud` / `usecases-ai` profiles stay as ad hoc
  targets. The A2A/MCP orchestrator still points at them.

## Why one data product, not thirteen

The first FEAT-019 design released the parent and all 12 domains as data products. The spike
found that demo.cloud is capped at **25 workspaces**: `GET /api/v1/entities/entitlements` returns
`WorkspaceCount = 25` with `Tier = DEMO`, and child workspaces count toward the cap. The org was
already full at 25/25. Thirteen data products would have needed 26 more workspaces there (dev +
test), and 26 more on the AI Usecases org. The user decided the 12-domain split had been a one-time
demo. GlobalMart is one parent workspace, and the domains remain derivable and deployable, not
deployed.

## Alternatives Considered

| Option | Pros | Cons |
|---|---|---|
| **Chosen: gdcloud, one data product, domains local-only** | Same release process as ecommerce; +2 workspaces per org; the domains keep every gate and stay one command from an org | The A2A/MCP demo needs `publish domains` before it runs |
| gdcloud, 13 data products (the first FEAT-019 design) | Every domain versioned and promoted | 52 workspaces across two capped orgs; 13 labels; a projector per domain |
| Raise the org's workspace cap and keep 13 | No design change | Depends on a plan change for a demo org; the split was a one-time demo anyway |
| Keep the bespoke `globalmart publish` path | Nothing to build | No versions, no promotion gate, no staging, and diverges from ecommerce on the same orgs |
| Stage B now: make `gd_data_product/globalmart/` the authoring tree | gdcloud's feature-branch workflows (1/2a/2b) become usable | Retires `layouts/` and `normalize.py`, amends ADR 001 and STEERING, and is a separate change from adopting the release. **Deferred at first, taken 2026-10-24** |

## Spike findings (FEAT-019 `spike.md`)

- gdcloud `v0.51.0`, `gooddata-sdk==1.75.0` and Python 3.14 resolve together. The whole suite
  passes. A git-pinned dependency needs `[tool.hatch.metadata] allow-direct-references = true`.
- gdcloud accepts labels like `GM_SALES` (no character-class rule), and maps MotherDuck to sqlglot
  `duckdb`.
- **The LDM had one reference cycle:** `dim_employee.department_id → dim_department` and
  `dim_department.manager_id → dim_employee`. The legacy whole-workspace PUT accepted it, but
  gdcloud's `put_declarative_ldm` rejects it. The department → employee reference was dropped and
  the `Manager ID (Department)` attribute kept, since nothing in the analytics model used the link.
- **The round trip is lossless.** A `gd-upload` → `gd-store` of the projected parent through a
  scratch workspace came back identical except for YAML formatting, the order of 14 memory items'
  `keywords` (set by the server), and an empty `workspace_data_filters.json`. Memory items,
  parameters, attribute hierarchies, dashboard extensions and export definitions all survive. The
  projector now emits exactly that form.

## Consequences

- **Positive:** Versioned releases (`v1.N`, `v1.N.M` hotfixes), promotion through staging, and
  PR-label-scoped deploys. There is one release story across both demo repos on the shared orgs,
  and goal-01 gains a reviewable, gated path from repo to org.
- **Negative:** The A2A/MCP demo is down until the domains are redeployed. The derived tree adds
  1781 committed files. Two project-owned workflows sit beside gdcloud's generated ones, and a pin
  bump that renames workflows 3/4/5 must not silently stop the post-deploy step. A test pins those
  names.
- **Neutral:** gdcloud's workflows 1/1b/2a/2b were adopted but not part of the routine path under
  Stage A, where a `gd-store` into the derived tree was drift. Stage B made them the routine path.

## Revisit Trigger

- gdcloud gains a pre/post-deploy hook. The post-deploy workflow would move into it.
- gdcloud titles masters per environment. The bootstrap's pre-creation step would retire.
- ~~Stage B is taken up: ADR 001 is amended and `layouts/` retires.~~ Taken 2026-10-24.
- A target needs a data source the rewrite cannot express (a different table layout, not just a
  different id and schema). gdcloud's env overrides would then be the place, not `resolve.py`.
- A domain needs to be live permanently, which would make the workspace cap the question again.

## Stage B (2026-10-24)

`gd_data_product/globalmart/` became the parent's only authoring tree, and `layouts/` retired. The
point is Services-MIC-Cloud parity: gdcloud's feature-branch workflows — create a dev workspace (1),
`gd-store` it back into the branch (2a), push the branch to it (2b) — are now legitimate edits
instead of drift.

- **One tree, in gdcloud's form.** It is the SDK's standard `store_to_disk` layout, so
  `layout_io.read_tree` is the SDK's own `load_from_disk`. `layout_io.write_tree` (used by
  `datefilters bind`, `knowledge build` and the pre-publish backup) stages the model and runs
  gdcloud's own `gd-format-yaml` normalizers over it, so a local write and a `gd-store` produce the
  same bytes; `read → write_tree` of the committed tree is byte-identical (a test pins it). Every
  reader — split, domains, publish, verify, rebuild, datefilters, knowledge, the generator's LDM
  foreign keys, data verify/load/ensure — defaults to it (`layout_io.DEFAULT_LAYOUT_PATH`).
- **The tree carries the canonical data source concretely** (`gd_data_product/config.env.yml`,
  `globalmart_canonical`: `gdc_ds_globalmart_motherduck` / `globalmart`). Publishing to a profile
  rewrites canonical id and schema to the profile's — dataset data source ids, table-path schemas,
  and SQL schema prefixes matched as whole dotted identifiers — and is a no-op when they match, as
  for every gdcloud environment. `demo-cloud-rebuild` (`globalmart-motherduck` / `globalmart_rebuild`)
  is the profile that exercises it. The safety stays: after the rewrite, any `{{ … }}` placeholder,
  any data source id other than the profile's, or any table schema other than the profile's fails
  the publish, rehearsal included.
- **The domain children carry the canonical data source too.** Regenerating
  `generated/workspaces/*.json` from the new source changed only form: 218 `{{ datasource_id }}` →
  `gdc_ds_globalmart_motherduck`, 248 `{{ datasource_schema }}` → `globalmart` (table paths and
  SQL), and 218 empty `workspaceDataFilterReferences: []` keys dropped, as gd-store drops them.
  Object sets and list order are unchanged; `publish domains` applies the same rewrite.
- **Capture is `gd-store`; `globalmart bootstrap` retired.** gd-store captures with
  `exclude=["ACTIVITY_INFO"]` (no user references), reverts gdcloud's env remaps, and writes the
  release form directly. A second capture path in this package would only be a second, drifting
  copy of it. `preflight.check_portability` still refuses audit fields on every publish.
- **`normalize.py` and `globalmart normalize` retired.** Nothing needs placeholders any more, and
  gdcloud's `gd-format-yaml --check` is the formatting gate: the "GoodData YAML Formatting Check"
  workflow in CI, `make lint` locally. The audit-field constants moved into `preflight.py`;
  `compare.mask_parameters` keeps its own mask strings for the cross-org proof.
- **The projection retired:** `gdcloud_project.py`, `globalmart gdcloud project`, `make project` /
  `project-check`, the `ci.yml` step and the `projection_current` gd-ci check. The
  `gdcloud.ci_checks` entry point stays, for `org_scope`.
- **`analytics_model/analytical_dashboard_extensions/` carried nothing.** The folder under
  `layouts/` was empty and untracked: the SDK's `load_from_disk` creates a folder for every
  collection it looks for (`parameters/`, `dashboard_plugins/`, `attribute_hierarchy_objects/`,
  `export_definitions/` too). The parent has 0 dashboard extensions, so nothing was lost and
  nothing was added to `gd_data_product/`. `read_tree` now removes those empty folders again.
- `gd_data_product/globalmart/` was left byte-identical by the change, so it needed no `GM` deploy.

