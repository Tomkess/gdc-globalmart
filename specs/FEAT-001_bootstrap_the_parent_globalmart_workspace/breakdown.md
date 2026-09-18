## Technical Breakdown — FEAT-001: Bootstrap the parent globalmart workspace into the repo as a gooddata-python-sdk native YAML layout tree, with a normalizer that makes the dump deterministic and diffable

> **Package name (used consistently below):** `globalmart`, laid out as `src/globalmart/` with a single console script `globalmart` declared in `pyproject.toml` under `[project.scripts]`. `scripts/bootstrap.py` is a two-line shim that calls `globalmart.cli:main` for people who prefer `uv run scripts/bootstrap.py`.

> **Steering conflict, resolved explicitly:** `STEERING.md` § Architecture Constraints says the parent lives under `layouts/gooddata_layouts/<org>/workspaces/globalmart/`, while § Portability Contract and the FEAT-001 acceptance criteria require a path with no org id. The Portability Contract wins: the tree lives at `layouts/workspaces/globalmart/`. Part of this feature is a one-line correction to `STEERING.md` so the two sections agree.

---

### Components

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|
| `src/globalmart/config.py` | Loads a named target profile (host, token, org id, datasource id, schema, parent workspace id) from `config/targets.yaml` + env overrides (`GLOBALMART_HOST`, `GLOBALMART_TOKEN`, …). Exposes `TargetProfile` (frozen dataclass) and `load_profile(name: str) -> TargetProfile`. Token is env-only, never read from the YAML file. | New | S |
| `src/globalmart/sdk_client.py` | Thin factory `make_sdk(profile: TargetProfile) -> GoodDataSdk` via `GoodDataSdk.create(host_, token_)`. Single place that touches credentials. | New | S |
| `src/globalmart/capture.py` | `capture_workspace(sdk, workspace_id) -> CatalogDeclarativeWorkspaceModel` using `sdk.catalog_workspace.get_declarative_workspace(workspace_id=...)`. Deliberately bypasses `store_declarative_workspace` / `layout_organization_folder()` (which would bake `petertomko` into the path via `layout_root_path / "gooddata_layouts" / organization_id`, `catalog_service_base.py:34-35`). Also captures the org-level WDF list via `sdk.catalog_workspace.get_declarative_workspace_data_filters()` purely so the normalizer can report on the 4 references it is about to handle. | New | S |
| `src/globalmart/normalize.py` | The heart of the feature. Pure, in-memory, model-level transform: `normalize_workspace(model: CatalogDeclarativeWorkspaceModel, *, datasource_token: str, schema_token: str, wdf_policy: WdfPolicy) -> NormalizeResult`. Structured traversal only — no regex over serialized JSON. Six passes, listed under **Data Model**. Idempotent by construction (`normalize(normalize(x)) == normalize(x)`, asserted in tests). | New | L |
| `src/globalmart/layout_io.py` | Deterministic writer/reader around the SDK. `write_tree(model, workspace_folder: Path)` calls `model.store_to_disk(workspace_folder=..., sort=True)` then post-processes every emitted `*.yaml` with our own dumper: `yaml.safe_dump(sort_keys=True, default_flow_style=False, allow_unicode=True, width=120, indent=2)` plus a trailing newline. Also performs **orphan pruning** — the SDK uses `create_directory`, not `recreate_directory`, so a re-capture that drops an object leaves a stale file behind; `write_tree` diffs written paths against the on-disk set and deletes the remainder. `read_tree(workspace_folder) -> CatalogDeclarativeWorkspaceModel` wraps `CatalogDeclarativeWorkspaceModel.load_from_disk(workspace_folder=...)`. | New | M |
| `src/globalmart/counts.py` | `count_objects(model) -> ObjectCounts` — the shared counter used by the bootstrap report, the round-trip test, and (later) FEAT-006. | New | S |
| `src/globalmart/cli.py` | `argparse`-based entry point with two subcommands: `globalmart bootstrap --target demo-cloud [--workspace-id globalmart] [--out layouts/workspaces/globalmart] [--dry-run]` and `globalmart normalize [--path layouts/workspaces/globalmart] [--check]`. `--check` exits 1 if normalization would change anything (CI gate). Prints the `NormalizeResult` report to stdout. | New | S |
| `layouts/workspaces/globalmart/` | The committed artifact: `ldm/datasets/*.yaml`, `ldm/date_instances/*.yaml`, `analytics_model/metrics/*.yaml`, `analytics_model/visualization_objects/*.yaml`, `analytics_model/analytical_dashboards/*.yaml`, `analytics_model/filter_contexts/*.yaml` (dir names come from the SDK's `LAYOUT_*_DIR` constants, so they are not ours to choose). | New (generated, committed) | — |
| `config/targets.yaml` | One entry per publish target. `demo-cloud` is the only one FEAT-001 needs; `local-inference` and `fresh-org` stubs are added so FEAT-002 is a config edit, not a code edit. | New | S |
| `tests/fixtures/mini_globalmart/` | A hand-trimmed, committed capture (~6 datasets, 8 metrics, 2 visualizations, 1 dashboard, 1 filter context, 1 SQL dataset, 1 WDF reference, `createdBy`/`modifiedBy` present) that exercises every normalizer pass without a live host. | New | M |
| `tests/` (5 modules, see Test Strategy) | Determinism, idempotency, portability-scrub, round-trip, and CLI tests. | New | M |
| `docs/bootstrap-provenance.md` | Records source host `petertomko.demo.cloud`, org id, workspace id `globalmart`, capture date, SDK version, and the captured object counts. Written by hand once; the counts are pasted from the `bootstrap` report. | New | S |
| `pyproject.toml` / `uv.lock` | Project scaffolding: Python 3.11+, deps `gooddata-sdk`, `PyYAML`; dev deps `pytest`, `ruff`, `mypy`. `[project.scripts] globalmart = "globalmart.cli:main"`. | New | S |
| `STEERING.md` | One-line correction of the parent-layout path to `layouts/workspaces/globalmart/`, matching the Portability Contract. | Existing | S |

---

### Data Model

**`TargetProfile`** (`config.py`, frozen dataclass; mirrors one entry in `config/targets.yaml`):

| Field | Type | Source | Example |
|---|---|---|---|
| `name` | `str` | YAML key | `"demo-cloud"` |
| `host` | `str` | YAML | `"https://petertomko.demo.cloud"` |
| `token` | `str` | env `GLOBALMART_TOKEN__DEMO_CLOUD`, fallback `GLOBALMART_TOKEN` | — |
| `organization_id` | `str` | YAML | `"petertomko"` |
| `datasource_id` | `str` | YAML | `"globalmart-motherduck"` |
| `datasource_schema` | `str` | YAML | `"main"` |
| `parent_workspace_id` | `str` | YAML, default `"globalmart"` | `"globalmart"` |

`organization_id`, `datasource_id` and `datasource_schema` are **capture inputs** here (what to scrub out) and **publish inputs** in FEAT-002 (what to substitute back in) — the same field, read in both directions, which is what makes the portability contract testable.

**Placeholder tokens** (`normalize.py` module constants, imported by FEAT-002 rather than re-declared):

```python
DATASOURCE_ID_TOKEN = "{{ datasource_id }}"
DATASOURCE_SCHEMA_TOKEN = "{{ datasource_schema }}"
```

**`WdfPolicy`** (`StrEnum`): `DROP` (default — call `model.remove_wdf_refs()`, the SDK's own structured traversal) or `KEEP` (leave the 4 references intact, for a target that has matching filter ids). Recorded in the report either way.

**The six normalizer passes**, by exact field path on the SDK model:

1. **User-reference scrub.** For every object inheriting `CatalogAnalyticsBaseMeta` (`CatalogDeclarativeMetric`, `…VisualizationObject`, `…AnalyticalDashboard`, `…FilterContext`, `…DashboardPlugin`, `…AttributeHierarchy`, `…ExportDefinition`): set `created_by = None`, `modified_by = None`, `created_at = None`, `modified_at = None`. (`created_by`/`modified_by` are `CatalogUserIdentifier | None`; the timestamps go too because they churn on every capture and would defeat byte-stability.) Expected: 420 `createdBy` + 1490 `modifiedBy` removed.
2. **Datasource parameterization.** For each `CatalogDeclarativeDataset` in `model.ldm.datasets`: if `dataset.data_source_table_id is not None`, set `.data_source_id = DATASOURCE_ID_TOKEN`; if `dataset.sql is not None`, set `dataset.sql.data_source_id = DATASOURCE_ID_TOKEN`. Expected: 225 rewrites. Field assignment on the attrs model — never string substitution on YAML text.
3. **Schema placeholder preservation.** For each dataset with `sql is not None`, assert `DATASOURCE_SCHEMA_TOKEN in dataset.sql.statement`; if the live statement contains the literal `profile.datasource_schema` instead, replace that identifier occurrence with the token. Never strip. A SQL dataset whose statement matches neither is collected into `NormalizeResult.unparameterized_sql` and the command exits non-zero — the failure mode that previously produced a silently broken publish.
4. **WDF handling.** Per `WdfPolicy`; `DROP` clears `dataset.workspace_data_filter_references` (and leaves `workspace_data_filter_columns` alone, since those are physical columns, not org-scoped ids). Expected: 4 references touched.
5. **List-order stabilization.** The SDK's `deep_sort` (`utils.py:467`) sorts mapping keys but **explicitly preserves list order**, so this pass is ours. Sort by natural key, in place: `ldm.datasets` by `id`; per dataset `attributes` by `id`, each attribute's `labels` by `id`, `facts` by `id`, `aggregated_facts` by `id`, `grain` by `(type, id)`, `references` by `identifier.id`, `tags` lexically; `ldm.date_instances` by `id`; `analytics.metrics` / `visualization_objects` / `analytical_dashboards` / `filter_contexts` / `attribute_hierarchies` / `export_definitions` by `id`. One-file-per-object means top-level list order only affects in-memory comparison, but nested lists land inside files and must be stable there.
6. **Empty-value canonicalization.** Normalize `[]` vs `None` on optional collection fields (`tags`, `aggregated_facts`, `dataset_extensions`, `workspace_data_filter_references`) to a single representation — `None` for optional scalars/collections, `[]` only where the SDK field is `field(factory=list)` — so two captures that differ only in how the API omitted an empty list produce identical bytes.

**`NormalizeResult`** (dataclass, the report the CLI prints and the tests assert against):

| Field | Type |
|---|---|
| `model` | `CatalogDeclarativeWorkspaceModel` |
| `user_refs_stripped` | `int` |
| `datasource_refs_rewritten` | `int` |
| `sql_datasets_parameterized` | `int` |
| `unparameterized_sql` | `list[str]` (dataset ids) |
| `wdf_refs_handled` | `int` |
| `wdf_policy` | `WdfPolicy` |
| `counts` | `ObjectCounts` |

**`ObjectCounts`** (`counts.py`): `datasets: int`, `date_instances: int`, `metrics: int`, `visualization_objects: int`, `analytical_dashboards: int`, `filter_contexts: int`, `attribute_hierarchies: int`, `dashboard_plugins: int`. Baseline asserted against the live workspace: 225 / 1075 / 384 / 32 for datasets / metrics / visualizations / dashboards.

No database and no new warehouse schema — the entire data model is the on-disk YAML tree plus `config/targets.yaml`.

---

### Integration Points

- **`gooddata-python-sdk`** — the only external dependency that matters. Used at exactly four points: `GoodDataSdk.create()`, `CatalogWorkspaceService.get_declarative_workspace(workspace_id, exclude=None)`, `CatalogDeclarativeWorkspaceModel.store_to_disk(workspace_folder=..., sort=True)`, `CatalogDeclarativeWorkspaceModel.load_from_disk(workspace_folder=...)`. `store_declarative_workspace` and `load_declarative_workspace` are **never** called — they route through `CatalogServiceBase.layout_organization_folder()`, which injects the org id into the path. A module docstring in `capture.py` records why.
- **`petertomko.demo.cloud` REST API** — read-only, via the SDK's layout API (`GET /api/v1/layout/workspaces/{id}`). Touched once during bootstrap and never again by any routine workflow. No raw REST calls are needed, so no SDK-gap comment is required.
- **The WDF org endpoint** — `get_declarative_workspace_data_filters()` is org-scoped, not workspace-scoped; it is read for reporting only and its output is not committed.
- **Git** — the tree is the deliverable. Determinism exists so that `git diff` is the review surface; a `.gitattributes` entry marks `layouts/**/*.yaml` as `text eol=lf` so a Windows checkout cannot break byte-stability.
- **FEAT-002 (publish)** consumes `read_tree()`, `DATASOURCE_ID_TOKEN`, `DATASOURCE_SCHEMA_TOKEN` and `TargetProfile` — the substitution direction is its job, but the vocabulary is defined here.
- **FEAT-003 / FEAT-004** consume `read_tree()` and the stable ids to build `domains.yaml` and to prune the LDM. FEAT-006 consumes `count_objects()`.
- **CI** — a job running `globalmart normalize --check` on the committed tree; it fails if anyone hand-edits a layout file into a non-canonical form.

---

### Test Strategy

All tests run against `tests/fixtures/mini_globalmart/` and never contact a host. `pytest`, invoked as `uv run pytest tests/ -x -q`.

**Unit — `tests/test_normalize.py`**
- Each of the six passes in isolation on a fixture model: user-ref scrub leaves zero `created_by`/`modified_by`; datasource rewrite hits both `data_source_table_id.data_source_id` and `sql.data_source_id`; schema pass preserves `{{ datasource_schema }}` and converts a literal `main.` occurrence to the token; a SQL dataset with neither lands in `unparameterized_sql`; WDF `DROP` vs `KEEP` behave as declared; nested label/attribute lists come back sorted.
- **Idempotency:** `normalize(normalize(m)) == normalize(m)` structurally (compare `to_api().to_dict()`).
- **Negative:** a fixture with a stripped schema (bare `FROM fact_orders`) must raise, not silently pass — this is the FEAT-004-adjacent bug class the spec calls out.

**Unit — `tests/test_layout_io.py`**
- Write the fixture model twice into two temp dirs; assert byte-identical files and identical file sets (the acceptance criterion "second capture ⇒ empty `git diff`", expressed without git).
- Orphan pruning: write a tree, delete a metric from the model, re-write, assert the stale `analytics_model/metrics/<id>.yaml` is gone.
- Assert no written path contains the org id `petertomko` and that the root is `layouts/workspaces/globalmart`, not `gooddata_layouts/`.

**Integration (offline) — `tests/test_round_trip.py`**
- `read_tree(fixture)` → `normalize()` → `write_tree(tmp)` → `read_tree(tmp)`; assert the two models are equal via `to_api().to_dict(camel_case=True)` after `deep_sort`. This is the "asserted by a test rather than eyeballed" criterion.
- Semantic-equality-modulo-parameters check: take the raw fixture capture (a second committed file, `tests/fixtures/raw_capture.json`, the un-normalized API payload for the mini workspace), normalize it, and diff against the normalized tree with the parameterized/stripped field paths masked. A leftover difference anywhere else fails the test.

**Unit — `tests/test_counts.py`** — `count_objects()` on the fixture returns the fixture's known counts; a guard test asserts the committed real tree's counts equal the numbers recorded in `docs/bootstrap-provenance.md` (parsed from that file, so the doc cannot drift).

**Unit — `tests/test_config.py`** — profile loading, env override precedence, missing-token error message, and that `targets.yaml` contains no token value.

**CLI smoke — `tests/test_cli.py`** — `normalize --check` on the fixture exits 0; on a deliberately de-normalized copy exits 1. `bootstrap --dry-run` with a stubbed `capture_workspace` writes nothing and prints a report.

**Manual, once** — run the real `globalmart bootstrap --target demo-cloud`, eyeball the report against 225 / 1075 / 384 / 32, grep the tree for `createdBy`, `modifiedBy`, `globalmart-motherduck` and `petertomko` (all must return zero hits), then run it a second time and confirm `git status` is clean. Record the outcome in `docs/bootstrap-provenance.md`.

---

### Total Effort Estimate

| Scale | Meaning |
|---|---|
| S | A few hours |
| M | 1–3 days |
| L | 1–2 weeks |
| XL | More than a sprint — consider splitting the feature |

**Overall: M–L (4–6 days).** The SDK does the file-per-object layout for free, so the bulk of the work is the normalizer's six passes plus the fixture. The two things that will eat the time are (a) building `tests/fixtures/mini_globalmart/` small enough to review but wide enough to cover every pass, and (b) chasing the last few sources of byte-instability once the real 225-dataset capture goes through — the `deep_sort`-preserves-list-order behavior means nested-list sorting has to be found field by field. Matches the spec's `m` appetite.

---

### Implementation Order

1. **`pyproject.toml` + `uv` scaffolding** — Python 3.11, `gooddata-sdk`, `PyYAML`, pytest/ruff/mypy, `[project.scripts] globalmart`. Nothing else can be imported until this exists.
2. **`config.py` + `config/targets.yaml`** — `TargetProfile`, `load_profile`, env-only token. Plus `tests/test_config.py`.
3. **`sdk_client.py` + `capture.py`** — the org-bypassing read path. Small, and it unblocks producing a real capture to trim into a fixture.
4. **`counts.py`** — needed by both the report and the tests that follow.
5. **`layout_io.py`** — `write_tree` (deterministic dump + orphan pruning) and `read_tree`. Built before the normalizer so determinism is provable on an un-normalized model first; `tests/test_layout_io.py` alongside.
6. **`tests/fixtures/mini_globalmart/`** — produced by running steps 3+5 against the live host once and hand-trimming, ensuring one of every shape (SQL dataset, WDF reference, populated `createdBy`, nested labels).
7. **`normalize.py`** — the six passes in the order listed under Data Model, each with its unit test before moving to the next. Passes 1–4 are independent; 5 and 6 must come last because they canonicalize whatever the earlier passes leave behind.
8. **`cli.py`** — `bootstrap` and `normalize --check`, wiring 2–7 together; `tests/test_cli.py`.
9. **`tests/test_round_trip.py`** — the acceptance harness; written once the pipeline is end-to-end runnable.
10. **The real capture** — run `globalmart bootstrap --target demo-cloud`, commit `layouts/workspaces/globalmart/`, verify the second run is a no-op.
11. **`docs/bootstrap-provenance.md` + `STEERING.md` path correction + `.gitattributes`** — provenance recorded from the real run's report, and the steering text brought in line with the neutral path.
12. **CI job** — `globalmart normalize --check` on the committed tree, so the invariant survives everyone who touches the repo after this.
