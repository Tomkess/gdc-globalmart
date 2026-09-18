## Tasks — FEAT-002: Publish the parent workspace from the repo YAML layout into any host/org/datasource, parameterized and idempotent, with no hardcoded identifiers

> Appetite: `s`  ·  Generated: 2026-09-18

- [x] 1. Create `src/globalmart/traversal.py` with the `DataSourceSlot` `NamedTuple` (`path: str`, `get: Callable[[], str | None]`, `set: Callable[[str], None]`) and `iter_datasource_slots(model) -> Iterator[DataSourceSlot]`, yielding one slot per `CatalogDeclarativeDataset.data_source_table_id.data_source_id` and one per `dataset.sql.data_source_id`, with `path` shaped as `ldm.datasets[<dataset_id>].sql.data_source_id`. Closures read and write the attrs model in place — no serialization anywhere in this module.
       Pre: FEAT-001 task 16 complete (normalizer pass 2 establishes the dataset/datasource traversal being lifted out), FEAT-001 task 11 complete (`tests/fixtures/mini_globalmart/`)
       AC: #4

- [x] 2. Add `iter_sql_statements(model) -> Iterator[tuple[str, Callable[[], str], Callable[[str], None]]]` to `traversal.py`, yielding `(dataset_id, get, set)` for every `dataset.sql.statement`, and `iter_all_string_fields(model) -> Iterator[tuple[str, str]]` — a defensive recursive walk of `model.to_api().to_dict()` yielding `(dotted_path, value)` for every string leaf, used only by the post-resolution assertion.
       Pre: task 1 complete (`traversal.py` module and `DataSourceSlot` exist)
       AC: #4, #5

- [x] 3. Write `tests/test_traversal.py`: on `tests/fixtures/mini_globalmart/`, `iter_datasource_slots()` yields the fixture's known slot count and every `path` is unique; a `set()` through a slot is visible on the model via `to_api().to_dict()`; `iter_sql_statements()` yields exactly the SQL-backed datasets; `iter_all_string_fields()` finds a sentinel string planted in a metric description (a field no enumerator visits).
       Pre: task 2 complete (all three generators implemented)
       AC: #4, #5

- [x] 4. Refactor `normalize.py` pass 2 (datasource parameterization) to write through `iter_datasource_slots()` instead of its own dataset loop, keeping `NormalizeResult.datasource_refs_rewritten` semantics identical. No behavior change: FEAT-001's `tests/test_normalize.py` and `tests/test_round_trip.py` must pass unmodified.
       Pre: task 3 complete (traversal proven against the fixture), FEAT-001 task 18 complete (pass 2/3 tests exist to prove no regression)
       AC: #4

- [x] 5. Refactor `normalize.py` pass 3 (schema placeholder preservation) onto `iter_sql_statements()`, so scrub and resolve share one enumeration of SQL statements. FEAT-001's pass-3 tests, including the `unparameterized_sql` negative fixture, must stay green unmodified.
       Pre: task 4 complete (pass 2 refactored; same module, do not interleave), FEAT-001 task 18 complete
       AC: #5

- [x] 6. Extend `src/globalmart/config.py`: add `WarehouseType` (`StrEnum`: `MOTHERDUCK = "motherduck"`, `POSTGRES = "postgres"`, any other YAML value raises at load time) and the base exception `GlobalmartError`; add the publish-side fields to the frozen `TargetProfile` — `warehouse_type`, `datasource_name`, `datasource_url`, `datasource_database: str | None`, `datasource_username: str | None`, `datasource_secret_env`, `workspace_id_prefix: str = ""`, `backup_dir: Path = Path("backups")`. `load_profile()` keeps its FEAT-001 signature.
       Pre: FEAT-001 task 3 complete (`TargetProfile`, `load_profile`)
       AC: #7, #8

- [x] 7. Implement `validate_for_publish(profile) -> list[str]` in `config.py`: returns the names of every publish-required key that is missing or empty, including `datasource_secret_env` when the named env var is itself unset or empty. Pure — it must not import the SDK or touch the network.
       Pre: task 6 complete (new `TargetProfile` fields and `WarehouseType`)
       AC: #7

- [x] 8. Fill in `config/targets.yaml`: complete `demo-cloud` (`warehouse_type: motherduck`, `datasource_name`, `datasource_url`, `datasource_database`, `datasource_secret_env`), `local-inference` (`warehouse_type: postgres`, `datasource_username`, its own `datasource_secret_env`) and the `fresh-org` stub. Zero secret values in the file — only env var names.
       Pre: task 6 complete (field names fixed by the dataclass)
       AC: #1, #9

- [x] 9. Extend `tests/test_config.py` (do not add a module): each profile loads with the correct `WarehouseType`; an unknown `warehouse_type` string raises at load time; `validate_for_publish()` on a profile with `datasource_url` blanked returns exactly `["datasource_url"]`; with the secret env var unset it names `datasource_secret_env`; and a re-assertion that `targets.yaml` contains no secret-shaped values at any depth.
       Pre: tasks 7 and 8 complete (validator and filled profiles)
       AC: #7, #9

- [x] 10. Create `src/globalmart/resolve.py` with the `ResolveResult` dataclass (`model`, `datasource_refs_resolved`, `sql_statements_resolved`, `schema_substitutions`, `unresolved_paths`, `foreign_datasource_ids`) and `resolve_placeholders(model, *, datasource_id, datasource_schema) -> ResolveResult`: set every `iter_datasource_slots()` slot to `datasource_id`, and replace `DATASOURCE_SCHEMA_TOKEN` (imported from `normalize.py`, never re-declared) with `datasource_schema` in every `iter_sql_statements()` statement — substituted, never stripped. A SQL dataset contributing zero substitutions is recorded as an error condition, not a warning. Pure and host-free.
       Pre: task 3 complete (generators proven), task 6 complete (`GlobalmartError` base)
       AC: #4, #5

- [x] 11. Add `assert_fully_resolved(model, *, datasource_id) -> None` and `UnresolvedLayoutError` to `resolve.py`: walk `iter_all_string_fields()` and raise listing every field path still containing `{{ ` plus every `dataSourceId` value not equal to `datasource_id` with its occurrence count; populate `unresolved_paths` and `foreign_datasource_ids` the same way so the report and the assertion cannot diverge.
       Pre: task 10 complete (`resolve_placeholders`, `ResolveResult`)
       AC: #4, #5

- [x] 12. Write `tests/test_resolve.py` part 1: on `mini_globalmart`, every slot from `iter_datasource_slots()` equals the profile's `datasource_id` after resolution and the count matches the fixture's known slot count; `{{ datasource_schema }}` is substituted — the resolved statement contains the target schema and not the token — plus a regression test asserting statement length grew, not shrank, for a schema longer than the token's replacement site.
       Pre: task 11 complete (resolve + assert implemented)
       AC: #4, #5

- [x] 13. Write `tests/test_resolve.py` part 2 — the predecessor-bug test and its siblings: a model whose datasource ids are `globalmart-motherduck` (neither the token nor the target) resolved with `datasource_id="globalmart-postgres"` must raise `UnresolvedLayoutError` naming every stale path; a `{{ ` token planted in a metric description is caught by `iter_all_string_fields()`; and the round trip `capture → normalize → resolve(with the capture's own profile)` equals the capture, compared on `to_api().to_dict(camel_case=True)`.
       Pre: task 12 complete (part 1 harness and fixtures in place)
       AC: #3, #4, #5

- [x] 14. Create `src/globalmart/compare.py` with `model_digest(model) -> str` — SHA-256 over `json.dumps(deep_sort(model.to_api().to_dict(camel_case=True)), sort_keys=True)` — and `model_diff(before, after) -> list[str]`, a flat, stable-sorted list of `path: old -> new` lines for the rehearsal report.
       Pre: task 11 complete (a resolved model is the thing being digested)
       AC: #2, #3

- [x] 15. Add `mask_parameters(model, profile) -> dict` to `compare.py`: return the `to_dict(camel_case=True)` form with every `dataSourceId` value and every occurrence of `profile.datasource_schema` in SQL statements replaced back by `DATASOURCE_ID_TOKEN` / `DATASOURCE_SCHEMA_TOKEN`, so two orgs' layouts compare equal under the parameterized set.
       Pre: task 14 complete (`compare.py` exists), task 10 complete (tokens imported from `normalize.py`)
       AC: #6

- [x] 16. Write `tests/test_compare.py`: `model_digest` is stable across two loads of the same tree and changes when one metric title changes; `model_diff` on identical models is empty and on a single-field change yields exactly one line naming the path; `mask_parameters` output contains neither the profile's `datasource_id` nor its `datasource_schema`.
       Pre: task 15 complete (all three functions implemented)
       AC: #3, #6

- [x] 17. Create `src/globalmart/datasource.py` with `build_data_source(profile)`: MotherDuck → `CatalogDataSourceMotherDuck` + `MotherDuckAttributes` + `TokenCredentials`; Postgres → `CatalogDataSourcePostgres` + `PostgresAttributes(host, port, db_name)` + `BasicCredentials(username, password)`; secret read from `os.environ[profile.datasource_secret_env]`. An unknown `warehouse_type` raises `UnsupportedWarehouseError` naming the type. The secret must never reach `repr()` or an exception message.
       Pre: task 6 complete (`WarehouseType`, secret-env field)
       AC: #8

- [x] 18. Add `DataSourceOutcome` (`StrEnum`: `CREATED`, `UPDATED`, `SKIPPED_NO_APPLY`) and `ensure_data_source(sdk, profile, *, apply: bool) -> DataSourceOutcome` to `datasource.py`: probe `get_data_source(profile.datasource_id)` to decide `CREATED` vs `UPDATED`, then call `create_or_update_data_source(build_data_source(profile))`; return `SKIPPED_NO_APPLY` and make no write call when `apply` is false.
       Pre: task 17 complete (`build_data_source`, `UnsupportedWarehouseError`)
       AC: #2, #8

- [x] 19. Write `tests/test_datasource.py`: MotherDuck profile yields `CatalogDataSourceMotherDuck` with `MotherDuckAttributes`/`TokenCredentials` and id, name and schema from the profile; Postgres profile yields `CatalogDataSourcePostgres` with `PostgresAttributes`/`BasicCredentials`; an unknown warehouse type raises `UnsupportedWarehouseError` naming the type; secret hygiene — the env value appears in no `repr()` of any built object and in no raised error message.
       Pre: task 18 complete (adapters and `ensure_data_source`)
       AC: #8

- [x] 20. Create `src/globalmart/preflight.py` with `check_profile(profile)` raising `MissingProfileKeyError` naming every key returned by `validate_for_publish()`. It must be callable — and called — before `make_sdk()`, so no credential or host contact can precede it.
       Pre: task 7 complete (`validate_for_publish`)
       AC: #7

- [x] 21. Add `check_organization(sdk, profile)` — `sdk.catalog_organization.get_organization()`, raising `OrganizationMismatchError` when `organization.id != profile.organization_id` — and `check_portability(model)`, which asserts zero `created_by` / `modified_by` survive anywhere in the model (via `iter_all_string_fields()` paths) and raises naming the offending paths, so a cross-org 400 is diagnosed locally.
       Pre: task 20 complete (`preflight.py` exists), task 2 complete (`iter_all_string_fields`)
       AC: #1, #7

- [x] 22. Write `tests/test_preflight.py`: a profile missing `datasource_url` raises `MissingProfileKeyError` naming exactly that key while `FakeSdk`-equivalent stub records zero calls; an unset `datasource_secret_env` value is reported as a missing key rather than a `KeyError` later; `check_organization` against a stub reporting a different org id raises `OrganizationMismatchError`; `check_portability` on a model carrying a `created_by` raises.
       Pre: task 21 complete (all three checks implemented)
       AC: #7

- [x] 23. Create `src/globalmart/backup.py` with `backup_workspace(sdk, profile, workspace_id) -> Path | None`: fetch the target's current layout with `get_declarative_workspace(workspace_id=...)`, write it through FEAT-001's `write_tree()` to `<profile.backup_dir>/<profile.name>/<workspace_id>/<UTC ISO-8601 basic timestamp>/`, and return `None` when the workspace does not exist (catch the SDK 404 and report "no prior content"). Add `backups/` to `.gitignore`.
       Pre: task 21 complete (the "workspace may not exist" path is defined alongside the org check), FEAT-001 task 9 complete (`write_tree`)
       AC: #1, #3

- [x] 24. Add `FakeSdk` to `tests/conftest.py`: a hand-written double (no mocking framework) recording ordered calls and arguments for `catalog_data_source.get_data_source`, `create_or_update_data_source`, `catalog_workspace.create_or_update`, `get_declarative_workspace` and `put_declarative_workspace`, plus `catalog_organization.get_organization`. `get_declarative_workspace` serves back whatever was last PUT, and is configurable to raise a 404 for the "no prior content" case.
       Pre: task 23 complete (the full set of SDK call sites FEAT-002 uses is now known)
       AC: #2, #3

- [x] 25. Create `src/globalmart/publish.py` with the `PublishResult` dataclass (`target`, `host`, `organization_id`, `workspace_id`, `datasource_id`, `datasource_outcome`, `workspace_created`, `backup_path`, `resolve`, `counts`, `digest_before`, `digest_after`, `changed`, `applied`) and `resolved_workspace_id(profile, base_id) -> str` applying `profile.workspace_id_prefix`.
       Pre: task 18 complete (`DataSourceOutcome`), task 14 complete (`model_digest`), task 10 complete (`ResolveResult`), FEAT-001 task 7 complete (`ObjectCounts`)
       AC: #1, #3

- [x] 26. Implement `publish_workspace(sdk, model, profile, *, workspace_id, apply: bool = False, standalone_copy: bool = False) -> PublishResult`, sequencing preflight → `ensure_data_source` → `resolve_placeholders` → `assert_fully_resolved` → `backup_workspace` → `create_or_update(CatalogWorkspace(...))` → `put_declarative_workspace(workspace_id, model, standalone_copy)`. Every one of the three write calls is gated on `apply`; the rehearsal still runs preflight, resolution, the assertion, the backup and the digests, and populates `digest_before`/`digest_after`/`changed`/`applied=False`. The display name comes from repo-side content, never from the target profile — the same GlobalMart published to two orgs must carry the same name (decided 2026-09-18). Define `PARENT_WORKSPACE_NAME = "GlobalMart"` in `publish.py`, expose `--workspace-name` to override it per invocation, and add no name field to `TargetProfile`; FEAT-004 passes each child's label from `domains.yaml` through the same parameter.
       Pre: task 25 complete (`PublishResult`, `resolved_workspace_id`), tasks 18, 21, 23 complete (datasource, preflight, backup callable)
       AC: #1, #2, #8

- [x] 27. Write `tests/test_publish.py` part 1 — happy path against `FakeSdk` with `apply=True`: exactly one `create_or_update_data_source`, one `create_or_update`, one `put_declarative_workspace`, recorded in that order, carrying the resolved model and `standalone_copy=False`; `datasource_outcome` is `CREATED` on an empty org and `UPDATED` when the probe finds one; `workspace_id_prefix` is applied identically to the `CatalogWorkspace` id and the PUT id.
       Pre: task 26 complete (`publish_workspace` orchestration), task 24 complete (`FakeSdk`)
       AC: #1, #8

- [x] 28. Write `tests/test_publish.py` part 2 — the safe default: calling `publish_workspace()` without `apply=True` records zero write calls on `FakeSdk` while still taking a backup and producing a `model_diff` (non-empty on a first publish, empty on a no-op republish); a separate test reads the signature and asserts the *default value* of `apply` is `False`, so the gate cannot be flipped silently.
       Pre: task 27 complete (happy-path harness and `FakeSdk` fixtures)
       AC: #2

- [x] 29. Write `tests/test_publish.py` part 3 — idempotency, backup and error surfacing: publish twice against a `FakeSdk` that serves back what it was given and assert the two PUT payload digests are identical and the second `PublishResult.changed is False`; a `FakeSdk` with no existing workspace yields `backup_path is None` and still publishes, one with content yields a readable tree under `tmp_path`; an SDK `ApiException` is re-raised with its response body verbatim in the message.
       Pre: task 28 complete (rehearsal tests), task 23 complete (`backup_workspace`)
       AC: #1, #3

- [x] 30. Extend `src/globalmart/cli.py` with the `publish` group and `publish parent --target <profile> [--workspace-id globalmart] [--from layouts/workspaces/globalmart] [--apply] [--no-backup] [--standalone-copy]`, loading the tree with `read_tree()` and never from a live org. Shape the group so FEAT-004 can add `publish domains` beside it without restructuring. `--standalone-copy` defaults to `False`; `--no-backup` is refused unless `--apply` is present, and when accepted prints a warning naming the workspace whose content will be unrecoverable.
       Pre: task 26 complete (`publish_workspace`), FEAT-001 task 25 complete (`cli.py`, `main()`, `read_tree` wiring)
       AC: #1, #2

- [x] 31. Implement the CLI report and exit codes: print the `PublishResult` (target, host, org, workspace id, datasource outcome, resolved counts, digests, `changed`), head a non-`--apply` run with the literal line `REHEARSAL — no writes. Re-run with --apply to publish.` followed by the `model_diff` lines, and exit 1 on any preflight, resolution or assertion failure, echoing an SDK `ApiException` response body verbatim.
       Pre: task 30 complete (subcommand parsed and wired)
       AC: #1, #2, #7

- [x] 32. Extend `tests/test_cli.py`: `publish parent` without `--apply` against `FakeSdk` exits 0, prints the rehearsal header and the diff, and records zero writes; `--no-backup` without `--apply` exits non-zero with a message naming the flag; `--no-backup --apply` proceeds and warns naming the workspace; a profile missing a key exits 1 naming the key with zero `FakeSdk` calls.
       Pre: task 31 complete (report and exit codes)
       AC: #2, #7

- [x] 33. Add `tests/fixtures/published_layouts/demo_cloud.json` and `local_inference.json` — the already-resolved layout dicts for the two profiles, generated from `mini_globalmart` by `resolve_placeholders` and committed — with a test asserting each regenerates byte-identically, so the fixtures cannot silently rot.
       Pre: task 13 complete (resolution proven), task 9 complete (both profiles fully specified)
       AC: #6

- [x] 34. Write `tests/test_cross_org.py`: publish the same fixture tree through the `demo-cloud` and `local-inference` profiles against two `FakeSdk` instances, capture both PUT payloads, run `mask_parameters()` on each, and assert the two are byte-identical — anything differing outside host, org, datasource id and schema fails.
       Pre: task 33 complete (committed resolved layouts), task 15 complete (`mask_parameters`), task 24 complete (`FakeSdk`)
       AC: #6

- [x] 35. Write `tests/test_no_hardcoded_identifiers.py`: walk `src/globalmart/**/*.py` and assert none of `petertomko`, `demo.cloud`, `globalmart-motherduck`, `globalmart-postgres` appears outside a comment; the code-level default `parent_workspace_id = "globalmart"` is explicitly allowed per STEERING § Architecture Constraints.
       Pre: task 31 complete (all FEAT-002 source modules written)
       AC: #9

- [x] 36. Write `docs/publish-targets.md`: every `TargetProfile` field with an example per warehouse type, which env var carries the GoodData token and which carries the warehouse secret, the explicit statement that a publish target is owned by the repo and will be overwritten wholesale by `put_declarative_workspace`, the `--apply` gate (link ADR 002), and where backups land (`backups/<target>/<workspace>/<UTC timestamp>/`, gitignored, directly republishable via `--from`).
       Pre: tasks 8, 23, 30 complete (profile fields, backup path, final CLI surface all fixed)
       AC: #1, #9

- [x] 37. **Requires explicit user approval to run against a live host.** Run `globalmart publish parent --target demo-cloud` (rehearsal, no `--apply`) and read the report: confirm 225 resolved datasource refs, zero `unresolved_paths`, zero `foreign_datasource_ids`, a plausible diff, and `applied is False` with nothing written to the org.
       Pre: tasks 32, 35 complete (offline suite green), task 8 complete (`demo-cloud` profile filled); credentials for `petertomko.demo.cloud` and the MotherDuck secret env var
       AC: #1, #2, #4, #5

- [x] 38. **Requires explicit user approval to run against a live host.** Run `globalmart publish parent --target demo-cloud --apply`, confirm the backup tree was written and the workspace carries the full LDM and analytics; then run it a third time with `--apply` and confirm `changed is False`, `datasource_outcome` is `UPDATED`, and no duplicated or orphaned objects.
       Pre: task 37 complete (rehearsal report reviewed and accepted)
       AC: #1, #3, #8

- [x] 39. **Requires explicit user approval to run against a live host.** Run `globalmart publish parent --target local-inference --apply` (Postgres adapter, first publish into that org), then fetch and normalize both orgs' resulting layouts and diff them under `mask_parameters()`; the only differences permitted are host, org, datasource id and schema. Record the outcome in `docs/publish-targets.md`.
       Pre: task 38 complete (demo-cloud published and proven idempotent); credentials for the local-inference host and its Postgres secret env var
       AC: #6, #8
