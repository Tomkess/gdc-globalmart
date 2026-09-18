## Tasks — FEAT-001: Bootstrap the parent globalmart workspace into the repo as a gooddata-python-sdk native YAML layout tree, with a normalizer that makes the dump deterministic and diffable

> Appetite: `m`  ·  Generated: 2026-09-18

- [ ] 1. Scaffold the `globalmart` package: create `pyproject.toml` (Python 3.11+, deps `gooddata-sdk` pinned to an exact version, `PyYAML`; dev deps `pytest`, `ruff`, `mypy`), `[project.scripts] globalmart = "globalmart.cli:main"`, `src/globalmart/__init__.py`, empty `tests/`, and generate `uv.lock` via `uv sync`. Verify `uv run python -c "import globalmart"` succeeds.
       Pre: none
       AC: #1

- [ ] 2. Add `config/targets.yaml` with a `demo-cloud` entry (host `https://petertomko.demo.cloud`, `organization_id: petertomko`, `datasource_id: globalmart-motherduck`, `datasource_schema: main`, `parent_workspace_id: globalmart`) plus commented `local-inference` and `fresh-org` stubs. No token values anywhere in the file.
       Pre: task 1 complete (`pyproject.toml`, repo layout)
       AC: #1

- [ ] 3. Implement `src/globalmart/config.py`: frozen dataclass `TargetProfile` (name, host, token, organization_id, datasource_id, datasource_schema, parent_workspace_id) and `load_profile(name: str) -> TargetProfile`. Token resolved env-only from `GLOBALMART_TOKEN__<NAME_UPPER_SNAKE>` then `GLOBALMART_TOKEN`; raise a named error listing both variables when absent. Host/org/datasource overridable via `GLOBALMART_HOST` etc.
       Pre: task 2 complete (`config/targets.yaml` schema fixed)
       AC: #1

- [ ] 4. Write `tests/test_config.py`: profile loads from `config/targets.yaml`; env override precedence (per-target token beats generic beats none); missing-token error message names both env vars; a test asserting `targets.yaml` parses and contains no `token` key at any depth.
       Pre: task 3 complete (`load_profile`, `TargetProfile`)
       AC: #1

- [ ] 5. Implement `src/globalmart/sdk_client.py`: `make_sdk(profile: TargetProfile) -> GoodDataSdk` via `GoodDataSdk.create(host_, token_)`. This is the only module that touches credentials; no other module may import the token field directly.
       Pre: task 3 complete (`TargetProfile`)
       AC: #1

- [ ] 6. Implement `src/globalmart/capture.py`: `capture_workspace(sdk, workspace_id) -> CatalogDeclarativeWorkspaceModel` via `sdk.catalog_workspace.get_declarative_workspace(workspace_id=...)`, plus `capture_wdf_list(sdk)` using `get_declarative_workspace_data_filters()` for reporting only. Module docstring records why `store_declarative_workspace` / `load_declarative_workspace` are never used (`catalog_service_base.py:34-35` bakes the org id into the path).
       Pre: task 5 complete (`make_sdk`)
       AC: #2

- [ ] 7. Implement `src/globalmart/counts.py`: `ObjectCounts` dataclass (datasets, date_instances, metrics, visualization_objects, analytical_dashboards, filter_contexts, attribute_hierarchies, dashboard_plugins) and `count_objects(model) -> ObjectCounts`, traversing `model.ldm` and `model.analytics` structurally.
       Pre: task 6 complete (a model object exists to count)
       AC: #7

- [ ] 8. Implement `src/globalmart/layout_io.py` part 1 — `write_tree(model, workspace_folder: Path)`: call `model.store_to_disk(workspace_folder=..., sort=True)`, then rewrite every emitted `*.yaml` with `yaml.safe_dump(sort_keys=True, default_flow_style=False, allow_unicode=True, width=120, indent=2)` and a trailing newline. Return the set of written paths.
       Pre: task 6 complete (`capture_workspace` yields a model to write)
       AC: #1, #6

- [ ] 9. Add orphan pruning and `read_tree` to `layout_io.py`: `write_tree` diffs its written-path set against the on-disk `*.yaml` set under `workspace_folder` and deletes the remainder (the SDK uses `create_directory`, not `recreate_directory`); `read_tree(workspace_folder) -> CatalogDeclarativeWorkspaceModel` wraps `CatalogDeclarativeWorkspaceModel.load_from_disk(workspace_folder=...)`.
       Pre: task 8 complete (`write_tree` returns written paths)
       AC: #2, #6

- [ ] 10. Write `tests/test_layout_io.py`: write the same model into two temp dirs and assert byte-identical file contents and identical file sets; orphan-pruning test (write, remove a metric from the model, re-write, assert the stale `analytics_model/metrics/<id>.yaml` is gone); assert no written path segment contains `petertomko` or `gooddata_layouts`.
       Pre: task 9 complete (`write_tree` with pruning, `read_tree`)
       AC: #2, #6

- [ ] 11. Produce `tests/fixtures/mini_globalmart/` by running capture (task 6) + `write_tree` (task 9) against the live host once and hand-trimming to ~6 datasets (one SQL-backed), 8 metrics, 2 visualizations, 1 dashboard, 1 filter context, 1 WDF reference, with `createdBy`/`modifiedBy`/timestamps left intact and at least one dataset carrying nested labels and a `grain`. Commit the trimmed tree.
       Pre: task 10 complete (deterministic writer proven); live read access to `petertomko.demo.cloud`
       AC: #1

- [ ] 12. Add `tests/fixtures/raw_capture.json` — the un-normalized API payload for the same mini workspace (saved from the task 11 capture before any normalization) — for the later semantic-equality-modulo-parameters test.
       Pre: task 11 complete (mini workspace trimmed and its object set fixed)
       AC: #8

- [ ] 13. Create `src/globalmart/normalize.py` skeleton: module constants `DATASOURCE_ID_TOKEN` and `DATASOURCE_SCHEMA_TOKEN`, `WdfPolicy` StrEnum (`DROP`/`KEEP`), `NormalizeResult` dataclass (model, user_refs_stripped, datasource_refs_rewritten, sql_datasets_parameterized, unparameterized_sql, wdf_refs_handled, wdf_policy, counts), and the `normalize_workspace(model, *, datasource_token, schema_token, wdf_policy) -> NormalizeResult` signature with passes stubbed. `DATASOURCE_ID_TOKEN` is the literal string `{{ datasource_id }}` — symmetric with the existing `{{ datasource_schema }}` placeholder, so one substitution mechanism covers both, and an unresolved token is greppable in a published layout (decided 2026-09-18).
       Pre: task 7 complete (`ObjectCounts` for the result), task 11 complete (fixture to develop against)
       AC: #4

- [ ] 14. Implement normalizer pass 1 (user-reference scrub): for every object inheriting `CatalogAnalyticsBaseMeta` (metrics, visualization objects, analytical dashboards, filter contexts, dashboard plugins, attribute hierarchies, export definitions) set `created_by`, `modified_by`, `created_at`, `modified_at` to `None`; count each removal into `user_refs_stripped`.
       Pre: task 13 complete (`normalize_workspace` skeleton, `NormalizeResult`)
       AC: #3

- [ ] 15. Test pass 1 in `tests/test_normalize.py`: after normalizing the fixture model, assert zero `created_by`/`modified_by`/`created_at`/`modified_at` survive across every analytics object type, and that `user_refs_stripped` equals the fixture's known count.
       Pre: task 14 complete (pass 1 implemented)
       AC: #3

- [ ] 16. Implement normalizer pass 2 (datasource parameterization): for each `CatalogDeclarativeDataset` in `model.ldm.datasets`, set `.data_source_id = DATASOURCE_ID_TOKEN` when `data_source_table_id is not None`, and `dataset.sql.data_source_id = DATASOURCE_ID_TOKEN` when `dataset.sql is not None`. Field assignment on the attrs model only — no string substitution. Count into `datasource_refs_rewritten`.
       Pre: task 13 complete (tokens defined)
       AC: #4

- [ ] 17. Implement normalizer pass 3 (schema placeholder preservation): for each dataset with `sql is not None`, keep `{{ datasource_schema }}` if present; if the statement carries the literal `profile.datasource_schema` identifier instead, replace that occurrence with the token; if neither is present, append the dataset id to `NormalizeResult.unparameterized_sql`. Never strip the placeholder.
       Pre: task 16 complete (dataset traversal in place)
       AC: #5

- [ ] 18. Test passes 2 and 3 in `tests/test_normalize.py`: both `data_source_table_id.data_source_id` and `sql.data_source_id` rewritten to the token; `{{ datasource_schema }}` preserved verbatim; a literal `main.` occurrence converted to the token; and a negative fixture with a bare `FROM fact_orders` lands in `unparameterized_sql` (must fail loudly, not pass silently).
       Pre: task 17 complete (passes 2 and 3 implemented)
       AC: #4, #5

- [ ] 19. Implement normalizer pass 4 (WDF handling): under `WdfPolicy.DROP` clear each dataset's `workspace_data_filter_references` (leaving `workspace_data_filter_columns` untouched); under `KEEP` leave them intact. Record `wdf_refs_handled` and `wdf_policy` in the report either way. Add a unit test covering both policies on the fixture's single WDF reference. Default is `WdfPolicy.DROP` — no WDF policy is in use today, so the 4 references in the parent are demo-org residue (decided 2026-09-18). `KEEP` stays implemented but unused, so a future row-level-security approach is a flag flip rather than a rewrite; FEAT-002's counterpart is `put_declarative_workspace(..., standalone_copy=True)`.
       Pre: task 13 complete (`WdfPolicy` defined), task 11 complete (fixture carries one WDF ref)
       AC: #2

- [ ] 20. Implement normalizer pass 5 (list-order stabilization): in-place sorts — `ldm.datasets` by `id`; per dataset `attributes` by `id`, each attribute's `labels` by `id`, `facts` by `id`, `aggregated_facts` by `id`, `grain` by `(type, id)`, `references` by `identifier.id`, `tags` lexically; `ldm.date_instances` by `id`; `analytics.metrics`, `visualization_objects`, `analytical_dashboards`, `filter_contexts`, `attribute_hierarchies`, `export_definitions` by `id`. The SDK's `deep_sort` preserves list order, so this pass is ours.
       Pre: tasks 14, 16, 17, 19 complete (passes 1–4 must run before canonicalization)
       AC: #6

- [ ] 21. Implement normalizer pass 6 (empty-value canonicalization): reduce `[]` vs `None` on optional collection fields (`tags`, `aggregated_facts`, `dataset_extensions`, `workspace_data_filter_references`) to one representation — `None` for optional scalars/collections, `[]` only where the SDK field is `field(factory=list)`.
       Pre: task 20 complete (pass 5 runs immediately before)
       AC: #6

- [ ] 22. Test passes 5, 6 and idempotency in `tests/test_normalize.py`: nested label/attribute/grain lists come back sorted; empty collections are canonical; and `normalize(normalize(m))` equals `normalize(m)` structurally, compared via `to_api().to_dict()`.
       Pre: task 21 complete (all six passes implemented)
       AC: #6

- [ ] 23. Add a credential-leak guard test (`tests/test_normalize.py`): after normalization and `write_tree`, scan every emitted YAML for credential-shaped keys (`token`, `password`, `secret`, `apiKey`, `clientSecret`, `privateKey`) and assert zero occurrences.
       Pre: task 21 complete, task 9 complete (`write_tree`)
       AC: #3

- [ ] 24. Write `tests/test_counts.py`: `count_objects()` on `tests/fixtures/mini_globalmart/` returns the fixture's known counts, and a guard test parses the counts table out of `docs/bootstrap-provenance.md` and asserts it equals `count_objects(read_tree("layouts/workspaces/globalmart"))` (skipped cleanly until the real tree and doc exist).
       Pre: task 7 complete (`count_objects`), task 11 complete (fixture)
       AC: #7

- [ ] 25. Implement `src/globalmart/cli.py`: `argparse` entry point `main()` with `globalmart bootstrap --target <name> [--workspace-id globalmart] [--out layouts/workspaces/globalmart] [--dry-run]` (load profile → make sdk → capture → normalize → write_tree → print `NormalizeResult`; `--dry-run` writes nothing) and `globalmart normalize [--path ...] [--check]` (read_tree → normalize → write or compare). Exit 1 when `unparameterized_sql` is non-empty, and exit 1 from `--check` when normalization would change any byte.
       Pre: tasks 3, 6, 9, 21 complete (config, capture, layout_io, normalizer all callable)
       AC: #1, #5, #6

- [ ] 26. Add `scripts/bootstrap.py` as a two-line shim calling `globalmart.cli:main`, for `uv run scripts/bootstrap.py` users.
       Pre: task 25 complete (`cli:main` exists)
       AC: #1

- [ ] 27. Write `tests/test_cli.py`: `normalize --check` on the fixture exits 0; on a deliberately de-normalized copy (re-ordered nested list, re-added `createdBy`) exits 1; `bootstrap --dry-run` with a stubbed `capture_workspace` writes no files and prints a report containing the counts.
       Pre: task 25 complete (both subcommands wired)
       AC: #6, #7

- [ ] 28. Write `tests/test_round_trip.py` part 1: `read_tree(fixture)` → `normalize()` → `write_tree(tmp)` → `read_tree(tmp)`, asserting the two models equal via `to_api().to_dict(camel_case=True)` after `deep_sort`. This is the "asserted by a test rather than eyeballed" criterion.
       Pre: tasks 9, 21 complete (read/write + normalizer), task 11 complete (fixture)
       AC: #8

- [ ] 29. Write `tests/test_round_trip.py` part 2: load `tests/fixtures/raw_capture.json`, normalize it, and diff against the normalized committed fixture tree with the parameterized/stripped field paths masked (`createdBy`, `modifiedBy`, `createdAt`, `modifiedAt`, `dataSourceId`, schema token, WDF refs). Any residual difference fails the test.
       Pre: task 28 complete (round-trip harness), task 12 complete (`raw_capture.json`)
       AC: #8

- [ ] 30. Add `.gitattributes` marking `layouts/**/*.yaml` and `tests/fixtures/**/*.yaml` as `text eol=lf`, so a Windows checkout cannot break byte-stability.
       Pre: task 9 complete (tree paths fixed)
       AC: #6

- [ ] 31. Run the real capture once: `globalmart bootstrap --target demo-cloud`, commit `layouts/workspaces/globalmart/`. Verify the report against 225 datasets / 1075 metrics / 384 visualizations / 32 dashboards, and grep the tree for `createdBy`, `modifiedBy`, `globalmart-motherduck` and `petertomko` (all must return zero hits). Requires explicit user approval to run against the live host. Also assert the AI-context objects are present in the capture (see task 31a) — a capture that silently drops them is a failed capture, not a clean one.
       Pre: tasks 25, 27 complete (CLI proven on the fixture); credentials for `petertomko.demo.cloud`
       AC: #1, #3, #4, #7

- [ ] 32. Verify determinism on the real tree: re-run `globalmart bootstrap --target demo-cloud` and assert `git status` is clean; if not, isolate the unstable field, add it to pass 5 or 6, and repeat until the second run is a byte-for-byte no-op.
       Pre: task 31 complete (real tree committed)
       AC: #6

- [ ] 31a. Carry the AI-context objects through capture and normalization: `memoryItems`, `parameters`, and any agent-personality / AI-knowledge objects the parent holds. They are **in scope and must survive cross-org publish** (decided 2026-09-18). Extend `count_objects()` with `memory_items` and `parameters` fields; extend normalizer pass 1 so user-scoped references *inside* these objects (`createdBy`/`modifiedBy`, author ids) are scrubbed while the content is preserved verbatim; add the objects to the pass-5 stable-sort list. Add a fixture object of each kind to `tests/fixtures/mini_globalmart/` and a unit test asserting content survives a capture → normalize → write → read round-trip byte-for-byte.
       Pre: task 16 complete (pass 1 implemented), task 21 complete (pass 5 implemented), task 7 complete (`ObjectCounts`)
       AC: #3, #8

- [ ] 33. Write `docs/bootstrap-provenance.md`: source host `petertomko.demo.cloud`, org id, workspace id `globalmart`, capture date, pinned SDK version, chosen `WdfPolicy`, and the captured object counts pasted from the task 31 report in the table shape `tests/test_counts.py` parses. Description health was checked against the 2026-06-25 export on 2026-09-18: 2713 descriptions, zero doubled — the predecessor's cleanup did land, so no cleanup feature is needed. Re-run the same check on the real capture and record the result, since the export predates later live mutations.
       Pre: task 31 complete (real report available), task 24 complete (parser shape defined)
       AC: #7

- [x] 34. ~~Correct `STEERING.md`: change the Architecture Constraints parent-layout path to `layouts/workspaces/globalmart/` so it agrees with the Portability Contract and the acceptance criteria.~~ **Already done 2026-09-18** — STEERING.md now names the neutral path and the `get_declarative_workspace(...).store_to_disk(workspace_folder=...)` read path. Verify only.
       Pre: task 31 complete (the real tree confirms the final path)
       AC: #2

- [ ] 35. Add the CI job running `uv run globalmart normalize --check layouts/workspaces/globalmart` plus `uv run pytest tests/ -x -q` on every PR, so a hand-edited layout file fails the build.
       Pre: tasks 25, 31 complete (CLI and committed tree both exist)
       AC: #6
