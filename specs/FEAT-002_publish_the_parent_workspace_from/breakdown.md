## Technical Breakdown — FEAT-002: Publish the parent workspace from the repo YAML layout into any host/org/datasource, parameterized and idempotent, with no hardcoded identifiers

> **Continuity with FEAT-001.** This feature adds no new package, no new CLI and no new config file. It extends `src/globalmart/` (console script `globalmart`, `[project.scripts]` in `pyproject.toml`), reuses `TargetProfile` / `load_profile()` from `config.py`, `make_sdk()` from `sdk_client.py`, `read_tree()` / `write_tree()` from `layout_io.py`, `count_objects()` / `ObjectCounts` from `counts.py`, and imports `DATASOURCE_ID_TOKEN` / `DATASOURCE_SCHEMA_TOKEN` from `normalize.py` rather than re-declaring them. FEAT-002 is the inverse direction of FEAT-001's normalizer passes 2 and 3.

> **The single invariant this feature exists to enforce.** The predecessor rewrote the datasource with `raw.replace('"globalmart-postgres"', f'"{datasource_id}"')` over serialized JSON — a no-op, because the real layout carried `globalmart-motherduck`, and it failed silently. Here, substitution happens only through one shared structured traversal (`traversal.py`), and every publish path — including the default no-`--apply` rehearsal — runs `assert_fully_resolved()` afterwards, which fails the command if a single placeholder token or a single datasource id other than the target's survives anywhere in the model. Nothing in this feature is allowed to touch serialized text.

---

### Components

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|
| `src/globalmart/config.py` | Extended with publish-side fields on `TargetProfile`: `warehouse_type: WarehouseType`, `datasource_name`, `datasource_url`, `datasource_database`, `datasource_username`, `datasource_secret_env`, `workspace_id_prefix`, `backup_dir`. Adds `WarehouseType` (`StrEnum`: `MOTHERDUCK`, `POSTGRES`) and `validate_for_publish(profile) -> list[str]`, which returns the names of every key required for publishing that is missing or empty — including the unresolved secret env var. `load_profile()` keeps its FEAT-001 signature; only the dataclass grows. | Existing — modified | S |
| `src/globalmart/traversal.py` | The one place that knows *where* datasource ids and schema references live in a `CatalogDeclarativeWorkspaceModel`. Exposes `DataSourceSlot` (a `NamedTuple` of `path: str`, `get: Callable[[], str \| None]`, `set: Callable[[str], None]`) and three generators: `iter_datasource_slots(model)` (yields a slot for every `CatalogDeclarativeDataset.data_source_table_id.data_source_id` and every `dataset.sql.data_source_id`). **Measured on the 2026-06-25 export: 225 datasets = 214 table-backed + 11 SQL-backed, mutually exclusive — no dataset carries both — so the generator yields exactly 225 slots, matching the 225 `dataSourceId` occurrences in the LDM.** A dataset carrying both would yield two slots; none does today, and `assert_fully_resolved` catches either shape regardless, `iter_sql_statements(model)` (yields `(dataset_id, get, set)` for every `dataset.sql.statement`), and `iter_all_string_fields(model)` (a defensive full walk of `model.to_api().to_dict()` used only by the post-resolution assertion, so a token hiding in a field nobody enumerated still gets caught). `normalize.py` passes 2 and 3 are refactored to consume the same generators, so scrub and resolve can never drift apart. | New (plus a refactor of existing `normalize.py`) | M |
| `src/globalmart/resolve.py` | The inverse of normalization, performed on the loaded model in memory. `resolve_placeholders(model, *, datasource_id: str, datasource_schema: str) -> ResolveResult` walks `iter_datasource_slots()` setting each slot to `datasource_id`, and `iter_sql_statements()` replacing `DATASOURCE_SCHEMA_TOKEN` with `datasource_schema` (substituted, never stripped — the FEAT-001 defect class). `assert_fully_resolved(model, *, datasource_id) -> None` then walks `iter_all_string_fields()` and raises `UnresolvedLayoutError` listing every field path that still contains `{{ `, plus every `dataSourceId` value not equal to `datasource_id`. Both functions are pure and host-free. | New | M |
| `src/globalmart/datasource.py` | Warehouse adapters. `build_data_source(profile) -> CatalogDataSourceMotherDuck \| CatalogDataSourcePostgres` — MotherDuck via `MotherDuckAttributes` + `TokenCredentials`, Postgres via `PostgresAttributes(host, port, db_name)` + `BasicCredentials(username, password)`, secret read from `os.environ[profile.datasource_secret_env]`. `ensure_data_source(sdk, profile) -> DataSourceOutcome` calls `sdk.catalog_data_source.create_or_update_data_source(build_data_source(profile))` and reports `CREATED` vs `UPDATED` by probing `get_data_source(profile.datasource_id)` first. An unknown `warehouse_type` raises `UnsupportedWarehouseError` naming the type — fails loudly, never silently. | New | M |
| `src/globalmart/preflight.py` | Everything that can fail before a byte is written. `check_profile(profile)` raises `MissingProfileKeyError` naming each key from `config.validate_for_publish()` — executed before `make_sdk()`, satisfying the "fails before contacting the host" criterion. `check_organization(sdk, profile)` calls `sdk.catalog_organization.get_organization()` and raises `OrganizationMismatchError` if `organization.id != profile.organization_id` — the guard against publishing over the wrong org with an over-scoped token. `check_portability(model)` asserts zero `created_by` / `modified_by` survived FEAT-001's scrub, so a cross-org 400 is diagnosed locally rather than read out of a server error body. | New | S |
| `src/globalmart/backup.py` | `backup_workspace(sdk, profile, workspace_id) -> Path \| None` fetches the target's current layout with `sdk.catalog_workspace.get_declarative_workspace(workspace_id=...)` and writes it through FEAT-001's `write_tree()` to `<profile.backup_dir>/<profile.name>/<workspace_id>/<UTC ISO-8601 basic timestamp>/`. Returns `None` when the workspace does not exist yet (the SDK raises on 404; caught and reported as "no prior content"). `backup_dir` defaults to `backups/`, which is gitignored — backups are local artifacts, never committed. | New | S |
| `src/globalmart/publish.py` | Orchestration. `publish_workspace(sdk, model, profile, *, workspace_id, apply: bool, standalone_copy: bool) -> PublishResult` runs: preflight → `ensure_data_source` → `resolve_placeholders` → `assert_fully_resolved` → `backup_workspace` → `sdk.catalog_workspace.create_or_update(CatalogWorkspace(id=workspace_id, name=...))` → `sdk.catalog_workspace.put_declarative_workspace(workspace_id, model, standalone_copy)`. **`apply` defaults to `False` and every write is gated on it** — see ADR 002. In the default rehearsal everything up to and including the assertion runs, the backup is still taken (it is a read), and the three write calls (datasource upsert, workspace upsert, layout PUT) are skipped; the diff from `compare.py` is printed instead. `ensure_data_source` returns `SKIPPED_NO_APPLY` in that mode. **Workspace display name** comes from repo-side content, not from the target profile — the same GlobalMart published to two orgs must carry the same name, so the name travels with the layout, not with the destination. `publish.py` defines `PARENT_WORKSPACE_NAME = "GlobalMart"`, overridable per invocation with `--workspace-name`; FEAT-004 passes each child's label from `domains.yaml` (e.g. `"GlobalMart — Sales"`) through the same parameter. `TargetProfile` gains no name field. `resolved_workspace_id(profile, base_id) -> str` applies `profile.workspace_id_prefix`, so several GlobalMart copies can coexist in one org for A/B eval runs (the spec's third open question, answered by a config field rather than by code). | New | M |
| `src/globalmart/compare.py` | Idempotency and cross-org equivalence, shared by the dry-run report and the tests. `model_digest(model) -> str` — SHA-256 over `json.dumps(deep_sort(model.to_api().to_dict(camel_case=True)), sort_keys=True)`. `model_diff(before, after) -> list[str]` — a flat list of `path: old -> new` lines for the dry-run report. `mask_parameters(model, profile) -> dict` — returns the dict form with `dataSourceId` values and schema occurrences replaced back by the FEAT-001 tokens, so two orgs' fetched layouts can be compared for the "identical except for the parameterized values" criterion. | New | S |
| `src/globalmart/cli.py` | Adds `globalmart publish parent --target <profile> [--workspace-id globalmart] [--from layouts/workspaces/globalmart] [--apply] [--no-backup] [--standalone-copy]`. **Without `--apply` the command is a read-only rehearsal** — it resolves, asserts, diffs and reports, and the report is headed with the line `REHEARSAL — no writes. Re-run with --apply to publish.` `--no-backup` is refused unless `--apply` is present (it is meaningless otherwise) and prints a warning naming the workspace whose content will be unrecoverable. Loads the tree with `read_tree()`, never from a live org. Prints the `PublishResult` report; exit code 1 on any preflight, resolution or assertion failure, with the server response body echoed verbatim on an SDK `ApiException`. The `publish` group is deliberately shaped so FEAT-004 can add `publish domains` beside it. | Existing — modified | S |
| `config/targets.yaml` | The `demo-cloud`, `local-inference` and `fresh-org` stubs FEAT-001 created are filled in with the new publish fields: `demo-cloud` → `warehouse_type: motherduck`, `local-inference` → `warehouse_type: postgres` with its own `datasource_secret_env`. Still zero secrets in the file. | Existing — modified | S |
| `tests/fixtures/mini_globalmart/` | Reused unchanged from FEAT-001 as the publish input. | Existing | — |
| `tests/fixtures/published_layouts/` | Two committed, already-resolved layout dicts (`demo_cloud.json`, `local_inference.json`) — what each target's layout looks like after resolution — used by the cross-org equivalence test without a host. | New | S |
| `tests/` (5 new modules, see Test Strategy) | `test_resolve.py`, `test_datasource.py`, `test_preflight.py`, `test_publish.py`, `test_cross_org.py`. | New | M |
| `docs/publish-targets.md` | One page: the fields of a target profile, which env var carries which secret, the statement that a publish target is owned by the repo and will be overwritten, and where backups land. | New | S |
| `.gitignore` | `backups/` added. | Existing — modified | S |

---

### Data Model

**`TargetProfile`** — FEAT-001's frozen dataclass, extended. FEAT-001 fields unchanged and re-read in the opposite direction (`datasource_id` and `datasource_schema` were *what to scrub out*; here they are *what to substitute in* — the same field, which is what makes the portability contract testable).

| Field | Type | Source | New in FEAT-002? | Example (`local-inference`) |
|---|---|---|---|---|
| `name` | `str` | YAML key | no | `"local-inference"` |
| `host` | `str` | YAML | no | `"https://gd.li.internal"` |
| `token` | `str` | env `GLOBALMART_TOKEN__LOCAL_INFERENCE` | no | — |
| `organization_id` | `str` | YAML | no | `"default"` |
| `datasource_id` | `str` | YAML | no | `"globalmart-postgres"` |
| `datasource_schema` | `str` | YAML | no | `"globalmart"` |
| `parent_workspace_id` | `str` | YAML, default `"globalmart"` | no | `"globalmart"` |
| `warehouse_type` | `WarehouseType` | YAML | **yes** | `WarehouseType.POSTGRES` |
| `datasource_name` | `str` | YAML | **yes** | `"GlobalMart Postgres"` |
| `datasource_url` | `str` | YAML | **yes** | `"jdbc:postgresql://db:5432/globalmart"` |
| `datasource_database` | `str \| None` | YAML (MotherDuck database / MD share name; `None` for Postgres, whose db is in the URL) | **yes** | `None` |
| `datasource_username` | `str \| None` | YAML (Postgres only) | **yes** | `"globalmart"` |
| `datasource_secret_env` | `str` | YAML — the *name* of the env var, never the value | **yes** | `"GLOBALMART_PG_PASSWORD"` |
| `workspace_id_prefix` | `str` | YAML, default `""` | **yes** | `"eval-a-"` |
| `backup_dir` | `Path` | YAML, default `Path("backups")` | **yes** | `backups/` |

**`WarehouseType`** (`config.py`, `StrEnum`): `MOTHERDUCK = "motherduck"`, `POSTGRES = "postgres"`. Any other value in YAML raises at profile-load time, not at publish time.

**`DataSourceSlot`** (`traversal.py`, `NamedTuple`): `path: str` (e.g. `"ldm.datasets[fact_orders].sql.data_source_id"`), `get: Callable[[], str | None]`, `set: Callable[[str], None]`. The only sanctioned way to read or write a datasource reference in either direction.

**`ResolveResult`** (`resolve.py`, dataclass) — deliberately parallel to FEAT-001's `NormalizeResult`:

| Field | Type |
|---|---|
| `model` | `CatalogDeclarativeWorkspaceModel` |
| `datasource_refs_resolved` | `int` (expected 225 on the real tree: 214 table-backed + 11 SQL-backed) |
| `sql_statements_resolved` | `int` (expected 11) |
| `schema_substitutions` | `int` (token occurrences replaced; a SQL dataset contributing 0 is an error, not a warning) |
| `unresolved_paths` | `list[str]` (field paths still containing `{{ `) |
| `foreign_datasource_ids` | `dict[str, int]` (id → occurrence count, for any id ≠ target's) |

`assert_fully_resolved()` raises `UnresolvedLayoutError` when either `unresolved_paths` or `foreign_datasource_ids` is non-empty. This is the assertion the spec's second risk row demands.

**`DataSourceOutcome`** (`datasource.py`, `StrEnum`): `CREATED`, `UPDATED`, `SKIPPED_NO_APPLY`.

**`PublishResult`** (`publish.py`, dataclass) — the report the CLI prints and the tests assert against:

| Field | Type |
|---|---|
| `target` | `str` (profile name) |
| `host` | `str` |
| `organization_id` | `str` |
| `workspace_id` | `str` (after prefix application) |
| `datasource_id` | `str` |
| `datasource_outcome` | `DataSourceOutcome` |
| `workspace_created` | `bool` |
| `backup_path` | `Path \| None` |
| `resolve` | `ResolveResult` |
| `counts` | `ObjectCounts` (FEAT-001's, reused verbatim) |
| `digest_before` | `str \| None` (`model_digest` of the fetched prior layout) |
| `digest_after` | `str` (`model_digest` of the model about to be / just PUT) |
| `changed` | `bool` (`digest_before != digest_after`) |
| `applied` | `bool` (`False` = rehearsal, nothing was written) |

**Exceptions** (all in the module that raises them, all subclasses of a single `GlobalmartError` added to `config.py`): `MissingProfileKeyError`, `OrganizationMismatchError`, `UnsupportedWarehouseError`, `UnresolvedLayoutError`.

No database, no new warehouse schema. The persisted state FEAT-002 adds is the gitignored `backups/<target>/<workspace>/<timestamp>/` tree, written in the same YAML form as the committed layout so a rollback is `globalmart publish parent --from backups/...`.

---

### Integration Points

- **`gooddata-python-sdk`** — five call sites beyond FEAT-001's four:
  - `sdk.catalog_data_source.create_or_update_data_source(data_source)` — upsert, satisfying the create-or-update criterion.
  - `sdk.catalog_data_source.get_data_source(datasource_id)` — probe only, to report `CREATED` vs `UPDATED`.
  - `sdk.catalog_workspace.create_or_update(CatalogWorkspace(id, name))` — workspace upsert.
  - `sdk.catalog_workspace.get_declarative_workspace(workspace_id=...)` — pre-publish backup and post-publish verification; the org-agnostic read path FEAT-001 established, never `load_declarative_workspace`.
  - `sdk.catalog_workspace.put_declarative_workspace(workspace_id, workspace, standalone_copy=False)` — the write. **REPLACE semantics**: it overwrites the workspace's content wholesale. This is the single most dangerous call in the repo and is why `backup.py` runs immediately before it.
  - Datasource types: `CatalogDataSourceMotherDuck` + `MotherDuckAttributes` + `TokenCredentials`; `CatalogDataSourcePostgres` + `PostgresAttributes` + `BasicCredentials`.
  - `standalone_copy=True` deep-copies the model and calls `workspace.remove_wdf_refs()` before the PUT. FEAT-001 already drops WDF refs at capture under `WdfPolicy.DROP`, so the flag is exposed (`--standalone-copy`) but defaults to `False` — see the tension note below.
- **Target GoodData orgs** — `petertomko.demo.cloud` (MotherDuck), the local-inference host (Postgres), and any fresh empty org. All three are reached only through a profile; none of their identifiers appears in code.
- **Warehouses** — the publisher registers a datasource but never queries it. Publishing against an empty warehouse must succeed; a failing datasource *test* connection is reported, not fatal, because FEAT-005 loads the rows afterwards and FEAT-006 verifies execution.
- **Environment** — two secrets per target: the GoodData API token (`GLOBALMART_TOKEN__<PROFILE>`, FEAT-001's convention) and the warehouse secret (`profile.datasource_secret_env`). Neither ever reaches `config/targets.yaml`, `docs/`, the report, or an exception message — `datasource.py` has a unit test asserting the secret string never appears in `repr()` of any built object or in a raised error.
- **FEAT-001** — consumes `read_tree()`, `write_tree()`, `TargetProfile`, `load_profile()`, `make_sdk()`, `count_objects()`, `ObjectCounts`, `DATASOURCE_ID_TOKEN`, `DATASOURCE_SCHEMA_TOKEN`; refactors `normalize.py` onto `traversal.py`.
- **FEAT-004** — the splitter publishes each child through `publish_workspace()` with a different model and `workspace_id`; nothing in `publish.py` may assume the parent. **FEAT-006** consumes `PublishResult.digest_after` and `counts` for its cold-rebuild smoke test.
- **CI** — the offline test suite runs on every PR. No CI job publishes to a live org; per STEERING § AI Behavior, live runs are explicitly user-initiated.

---

### Test Strategy

Everything runs offline against committed fixtures, `uv run pytest tests/ -x -q`. The SDK is exercised through a hand-written `FakeSdk` in `tests/conftest.py` — recording `create_or_update_data_source`, `create_or_update`, `get_declarative_workspace` and `put_declarative_workspace` calls with their arguments — rather than a mocking framework, so the assertions read as "what was sent to the host".

**Unit — `tests/test_resolve.py`** (the core of the feature)
- Every slot from `iter_datasource_slots()` on `mini_globalmart` comes back equal to the profile's `datasource_id`; count matches the fixture's known slot count.
- `{{ datasource_schema }}` is **substituted**, not stripped: the resolved SQL statement contains the target schema and does not contain the token. A regression test asserts the statement length grew rather than shrank for a schema longer than the token's replacement site.
- **The predecessor-bug test:** build a model whose datasource ids are `globalmart-motherduck` (not the token, not the target), run `resolve_placeholders` + `assert_fully_resolved` with `datasource_id="globalmart-postgres"`, and assert it raises `UnresolvedLayoutError` naming every stale path. The predecessor's string-replace would have passed this silently; this test is the feature.
- A token planted in a field *not* enumerated by `iter_datasource_slots()` (e.g. a metric description) is still caught by `iter_all_string_fields()`.
- `resolve(normalize(m))` restores the original ids: the round-trip `capture → normalize → resolve(with the capture's own profile)` equals the capture, asserted on `to_api().to_dict(camel_case=True)`.

**Unit — `tests/test_datasource.py`**
- MotherDuck profile → `CatalogDataSourceMotherDuck` with `MotherDuckAttributes` and `TokenCredentials`, id/name/schema from the profile.
- Postgres profile → `CatalogDataSourcePostgres` with `PostgresAttributes` and `BasicCredentials`.
- An unknown `warehouse_type` raises `UnsupportedWarehouseError` naming the type.
- Secret hygiene: the env value appears in no `repr()` and in no exception message.

**Unit — `tests/test_preflight.py`**
- A profile missing `datasource_url` fails with `MissingProfileKeyError` naming exactly that key, and `FakeSdk` records **zero** calls — the "fails before contacting the host" criterion asserted structurally.
- A missing `datasource_secret_env` value is reported as a missing key, not as a `KeyError` at PUT time.
- `check_organization` against a `FakeSdk` reporting a different org id raises `OrganizationMismatchError` and nothing is written.
- `check_portability` on a model carrying a `created_by` raises before the PUT.

**Integration (offline) — `tests/test_publish.py`**
- Happy path against `FakeSdk`: exactly one `create_or_update_data_source`, one `create_or_update`, one `put_declarative_workspace`, in that order, with the resolved model and `standalone_copy=False`.
- **Idempotency:** publish twice against a `FakeSdk` that serves back what it was given; assert `model_digest` of the two PUT payloads is identical and the second `PublishResult.changed is False`. This is the acceptance criterion expressed without a host.
- **Default is safe:** calling `publish_workspace()` without `apply=True` records **zero** write calls on `FakeSdk` (no datasource upsert, no workspace upsert, no PUT) while still taking a backup and producing a `model_diff` — non-empty on a first publish, empty on a no-op republish. A separate test asserts the *default value* of the `apply` parameter is `False`, so the safe default cannot be flipped by accident.
- `--no-backup` without `--apply` is rejected at the CLI layer; `--no-backup --apply` proceeds and the warning text names the workspace.
- Backup: a `FakeSdk` with no existing workspace yields `backup_path is None` and still publishes; one with existing content yields a readable tree under `tmp_path`.
- `workspace_id_prefix` is applied to the `CatalogWorkspace` id and the PUT id consistently.
- An SDK `ApiException` is surfaced with its response body verbatim in the raised message.

**Unit — `tests/test_cross_org.py`**
- Publish the same fixture tree through two different profiles, capture both PUT payloads, run `mask_parameters()` on each, and assert the two are byte-identical. The parameterized values (host, org, datasource id, schema) are exactly the masked set; anything else differing fails. This is the spec's fifth criterion, offline.

**Static — `tests/test_no_hardcoded_identifiers.py`**
- Walk `src/globalmart/**/*.py` and assert none of `petertomko`, `demo.cloud`, `globalmart-motherduck`, `globalmart-postgres` appears outside a comment. The spec's last criterion, mechanized so it cannot rot.

**Manual, once, user-initiated (per STEERING § AI Behavior)**
- `globalmart publish parent --target demo-cloud` (rehearsal), read the report, confirm 225 resolved refs and zero unresolved paths. Then the same command with `--apply`. Then a third run with `--apply` and confirm `changed is False`. Then `globalmart publish parent --target local-inference --apply` and diff the two orgs' fetched-and-normalized layouts, which must differ only in the parameterized values.

---

### Total Effort Estimate

| Scale | Meaning |
|---|---|
| S | A few hours |
| M | 1–3 days |
| L | 1–2 weeks |
| XL | More than a sprint — consider splitting the feature |

**Overall: M (2–3 days).** The SDK supplies the upsert and PUT verbs, so the real work is (a) `traversal.py` — enumerating every place a datasource id or schema can hide on the attrs model, and retrofitting `normalize.py` onto it without regressing FEAT-001's tests, and (b) the `FakeSdk` plus the cross-org masking test, which is what makes the whole thing provable offline. The two warehouse adapters are half a day. Matches the spec's `s` appetite, on the assumption that FEAT-001 has landed — if `traversal.py` has to be invented against an un-captured tree, add a day.

---

### Implementation Order

1. **`traversal.py`** — `DataSourceSlot`, the three generators, and the refactor of `normalize.py` passes 2 and 3 onto them. FEAT-001's existing tests must stay green; this step adds no behavior. Everything else depends on it.
2. **`config.py` extension + `config/targets.yaml` fill-in** — the new `TargetProfile` fields, `WarehouseType`, `validate_for_publish()`. Extend `tests/test_config.py` rather than adding a module.
3. **`resolve.py` + `tests/test_resolve.py`** — `resolve_placeholders` and `assert_fully_resolved`, including the predecessor-bug test. Pure and host-free, so it is testable the moment step 1 exists, and it is the feature's whole point.
4. **`compare.py`** — `model_digest`, `model_diff`, `mask_parameters`. Needed by the dry-run report and by three later test modules.
5. **`datasource.py` + `tests/test_datasource.py`** — the two adapters and the loud failure for a third warehouse type.
6. **`preflight.py` + `tests/test_preflight.py`** — profile completeness, org-identity pin, portability assertion. Built before anything can write.
7. **`backup.py`** — reuses `write_tree()`; trivial once step 6 defines the "workspace may not exist" path. `.gitignore` entry lands here.
8. **`publish.py` + `tests/conftest.py` `FakeSdk` + `tests/test_publish.py`** — orchestration, dry-run, idempotency. The `FakeSdk` is written here and reused by steps 9–10.
9. **`cli.py` — `publish parent` subcommand** — wiring 2–8 together, the report, exit codes, verbatim server errors. Extend `tests/test_cli.py`.
10. **`tests/test_cross_org.py` + `tests/fixtures/published_layouts/` + `tests/test_no_hardcoded_identifiers.py`** — the acceptance harness, written once the pipeline is end-to-end runnable offline.
11. **`docs/publish-targets.md`** — profile fields, secret env vars, the "targets are owned by the repo and will be overwritten" statement, backup location.
12. **The real publishes (user-initiated)** — `demo-cloud` dry-run, `demo-cloud`, a second `demo-cloud` run to prove idempotency, then `local-inference`, then the cross-org normalized diff.

---

### Open Questions — answered by this breakdown

The spec's four open questions are resolved here so `/tasks` has no ambiguity to carry:

- **Drift detection vs always overwrite** → always overwrite, but never blind and never by default: writes are gated on `--apply` (ADR 002), a mandatory pre-publish backup runs immediately before the PUT, and `PublishResult.digest_before`/`changed` make the drift visible in the report. The default rehearsal shows the diff before any write exists.
- **Where backups live** → gitignored local `backups/<target>/<workspace>/<UTC timestamp>/`, written as a YAML tree by `write_tree()` so it is directly republishable. No object storage.
- **One profile per (org × warehouse), or a workspace-id prefix too** → both: `workspace_id_prefix` (default `""`) is a profile field, so several GlobalMart copies coexist in one org for A/B eval runs without a second profile.
- **Does local inference need a different credential mechanism** → yes, and it is already a profile field: `warehouse_type: postgres` selects `BasicCredentials` with `datasource_username` + `datasource_secret_env`, against MotherDuck's `TokenCredentials`. No code change to add a third.
