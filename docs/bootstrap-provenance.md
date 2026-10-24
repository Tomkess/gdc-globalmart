# Bootstrap provenance

Where the committed parent layout came from, and when. (Historical: the tree has lived in
`gd_data_product/globalmart/` since 2026-10-24, and `globalmart bootstrap` is retired — see the
last section.) This file exists so a future reader
never has to guess whether the tree is current, or which org it was taken from.

`tests/test_counts.py` parses the table below and asserts it matches the committed tree, so
the doc cannot silently drift.

## Capture

| | |
|---|---|
| Source host | `https://petertomko.demo.cloud.gooddata.com` |
| Source organization | `petertomko` |
| Source workspace | `globalmart` |
| Captured | 2026-09-18 |
| gooddata-sdk | `1.75.0` |
| Command | `globalmart bootstrap --target demo-cloud` |
| WDF policy | `drop` (no WDF policy is in use; the references were demo-org residue) |
| Files written | 1766 |

## Object counts

| Channel | Count |
|---|---|
| `datasets` | 225 |
| `date_instances` | 2 |
| `dataset_extensions` | 0 |
| `metrics` | 1091 |
| `visualization_objects` | 384 |
| `analytical_dashboards` | 32 |
| `analytical_dashboard_extensions` | 0 |
| `filter_contexts` | 32 |
| `attribute_hierarchies` | 0 |
| `dashboard_plugins` | 0 |
| `export_definitions` | 0 |
| `memory_items` | 14 |
| `parameters` | 0 |

## What normalization did

| Pass | Result |
|---|---|
| user references stripped | 4923 |
| datasource references parameterised | 225 |
| SQL datasets schema-parameterised | 11 |
| WDF references handled | 0 |

## Notes

- **The schema was hardcoded, not templated.** All 11 SQL datasets carried a literal
  `globalmart.` prefix at capture time; none carried `{{ datasource_schema }}`. The
  substitution had been performed historically and written back to the live org, so the
  normalizer *introduces* the placeholder rather than preserving one.
- **The datasource reports `schema: globalmart`**, not `main`. Taken from the live
  datasource definition rather than assumed.
- **The LDM uses no labels.** Zero nested labels across all 225 datasets.
- **Live had drifted from the last committed export.** 1091 metrics here against 1075 in
  the 2026-06-25 export in the predecessor repo — 16 added since, plausibly eval artifacts.
  FEAT-001 captures reality deliberately; cleaning them is a separate, reviewable change.
- **AI context channels are empty today** (0 memory items, 0 parameters). They are still
  captured and counted, and `tests/test_sdk_floor.py` pins the SDK version that models
  them — on an older SDK they would be dropped silently.

## Amended 2026-09-20 — memory items (FEAT-008)

`memory_items` was 0 at capture and is now **14**. Those items are not captured content:
they are compiled from `docs/knowledge/*.md` by `globalmart knowledge build`, and they are
the first content GlobalMart has ever had in an AI channel.

They carry the reserved tag `knowledge`, which is what distinguishes them from anything a
capture pulls back. A re-`bootstrap` against an org that lacks them will remove them from
the tree — correct, since the tree mirrors the org — so the ordering is **bootstrap, then
knowledge build, then publish**. See `docs/knowledge.md`.

## Amended 2026-10-24 — ADR 011 Stage B

The tree moved from `layouts/workspaces/globalmart/` to `gd_data_product/globalmart/`, the folder
gdcloud releases, and is now authored there directly. The capture above is still its origin; the
object counts are unchanged and still pinned by `tests/test_counts.py`, against the new path.

- **`globalmart bootstrap` and `globalmart normalize` are retired.** A capture is gdcloud's
  `gd-store` (`make store`, or workflow 2a from a dev workspace). It excludes activity info, so no
  user references reach the tree, and it writes gdcloud's exact YAML form; `gd-format-yaml --check`
  is the formatting gate.
- **No placeholders any more.** The tree carries the canonical data source concretely
  (`gdc_ds_globalmart_motherduck` / `globalmart`, from `gd_data_product/config.env.yml`); a publish
  rewrites it to the target's. The SQL datasets' `globalmart.` prefixes are therefore literal again
  — on purpose this time.
- The ordering for memory items becomes **gd-store, then knowledge build, then publish**: a
  `gd-store` from a workspace that lacks the compiled items removes them, and `knowledge build
  --check` in CI catches it.

