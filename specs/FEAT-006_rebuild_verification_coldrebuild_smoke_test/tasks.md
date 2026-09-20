## Tasks — FEAT-006: Rebuild verification: cold-rebuild smoke test that executes every visualization in the parent and every domain workspace and reports failures

> Appetite: `m`  ·  Generated: 2026-09-18

- [x] 1. Create `src/globalmart/classify.py` with `FailureCategory` (`StrEnum`, 13 members: the predecessor's `WDF_NO_VALUE`, `PROTECTED`, `INVALID_IDENTIFIER`, `LDM_MAPPING`, `DATA_LIMIT`, `CALC_ERROR`, `TOO_LARGE_TIMEOUT`, `TRANSIENT_5XX`, `UNSUPPORTED_TYPE`, `TIMEOUT`, `UNKNOWN` plus `RATE_LIMITED` and `EMPTY_RESULT`), the `Failure` `NamedTuple` (`category`, `hint`), and `_HINTS` carrying one remediation sentence per category. Port the hint text from `Misc/scripts/classifier.py` verbatim where the category is unchanged.
       Pre: FEAT-002 task 6 complete (`GlobalmartError` base in `config.py`); `Misc/scripts/classifier.py` read as the source of the taxonomy
       AC: #2

- [x] 2. Implement `classify(error: str, status: int | None) -> Failure` in `classify.py` with the predecessor's priority order (WDF → protected → data limit → too-large → invalid identifier → LDM mapping → calc error → unsupported type → 5xx → timeout → unknown), plus a `RATE_LIMITED` rule on `status == 429` placed above the 5xx rule. Add `extract_status(exc) -> int | None` (the `HTTP nnn` / `status: nnn` / `(nnn)` / `Reason: nnn` regex) and `is_retryable(category) -> bool`, true for exactly `TRANSIENT_5XX` and `RATE_LIMITED`. Pure — no SDK import, no network.
       Pre: task 1 complete (`FailureCategory`, `Failure`, `_HINTS`)
       AC: #2, #11

- [x] 3. Add `tests/fixtures/verification/errors/` — one `.txt` file per taxonomy category holding a real-shaped server error body (WDF "filter values ... are empty" 400, a `ProtectedReportSdkError`, an xtab-rows limit, a "report is too large", a 404 not-found, an unmapped-LDM warning, a "while calculating the result" 400, a bare `'properties'` `KeyError`, a 503, a 429, a timeout sentinel, and two deliberately ambiguous bodies that match two rules).
       Pre: task 2 complete (the rule set fixes which bodies are needed)
       AC: #2

- [x] 4. Write `tests/test_classify.py`: parametrized over the fixture directory, each body classifies to its expected category with a non-empty hint; the ambiguous body matching both the WDF and the calc-error signals classifies `WDF_NO_VALUE` (workspace-wide cause wins over per-object); `extract_status` recovers 500 from all four string shapes and `None` from a body with no status; `is_retryable` is true for exactly two categories and false for the other eleven.
       Pre: task 3 complete (error fixtures committed)
       AC: #2, #11

- [x] 5. Extend `FakeSdk` in `tests/conftest.py` with `visualizations.get_visualizations(workspace_id)` returning a configurable per-workspace object list (each object carrying `id` and `title`), and `catalog_workspace.list_workspaces()` returning a configurable id list. Do not alter the FEAT-002 call recorders — FEAT-002's tests must pass unmodified.
       Pre: FEAT-002 task 24 complete (`FakeSdk` exists with its five recorders)
       AC: #12

- [x] 6. Add a programmable `tables.for_visualization(workspace_id, viz, always_two_dimensional)` to `FakeSdk`, dispatching per viz id to one of five behaviours: return a table with N rows, return a zero-row table, raise an `ApiException` carrying a canned body and status, sleep past a given duration, or raise `KeyError('properties')`. Record every call with its arguments and timestamp, and track the maximum number of simultaneously in-flight calls so a concurrency bound can be asserted.
       Pre: task 5 complete (`FakeSdk` extended with the visualization list)
       AC: #12, #11

- [x] 7. Create `src/globalmart/execute.py` with `ExecStatus` (`StrEnum`: `OK`, `EMPTY`, `BROKEN`, `SKIPPED`) and the `VizResult` dataclass (`workspace_id`, `viz_id`, `title`, `status`, `duration_ms`, `attempts`, `row_count: int | None`, `column_count: int | None`, `error: str | None`, `http_status: int | None`, `category: FailureCategory | None`, `hint: str | None`).
       Pre: task 2 complete (`FailureCategory` for the result fields)
       AC: #1, #2, #3

- [x] 8. Implement `execute_visualization(sdk, workspace_id, viz, *, timeout_s: int, max_retries: int, throttle) -> VizResult` in `execute.py`: run `sdk.tables.for_visualization(workspace_id, viz, always_two_dimensional=True)` inside an inner daemon thread joined with a hard `timeout_s` (a `ThreadPoolExecutor` cannot cancel an in-flight task — this is the predecessor's pattern and the reason for it goes in the docstring); derive `row_count`/`column_count` from the returned table and set `EMPTY` on zero rows, `OK` otherwise; record `error` as the server's body **verbatim and untruncated**, with `http_status` from `extract_status`; map `KeyError('properties')` to `SKIPPED` with category `UNSUPPORTED_TYPE`; record a join-timeout as `BROKEN` with category `TIMEOUT`.
       Pre: task 7 complete (`VizResult`, `ExecStatus`), task 2 complete (`classify`, `extract_status`)
       AC: #1, #2, #3

- [x] 9. Add the retry policy to `execute_visualization`: retry only when `is_retryable(category)`, up to `max_retries`, with exponential backoff, and record the true `attempts` on the result so a pass on attempt 3 is visible rather than silently green. A non-retryable failure must record `attempts=1` and make exactly one SDK call.
       Pre: task 8 complete (single-shot execution path)
       AC: #11

- [x] 10. Add `Throttle` to `execute.py`: a class wrapping a `threading.Semaphore` as the live concurrency budget shared by the whole run, with `acquire()`/`release()`, `halve(trigger: str, workspace_id: str)` which drops the budget to at least 1 and appends a `ThrottleEvent` (`workspace_id`, `at`, `from_workers`, `to_workers`, `trigger`), and `reset()` called at each workspace boundary. `execute_visualization` calls `halve` on a `RATE_LIMITED` result and on a configurable burst of consecutive `TRANSIENT_5XX`.
       Pre: task 9 complete (retry policy defines where a 429/5xx is observed)
       AC: #11

- [x] 11. Implement `execute_workspace(sdk, workspace_id, *, pool: ThreadPoolExecutor, throttle, timeout_s, max_retries, on_progress) -> list[VizResult]`: list objects with `sdk.visualizations.get_visualizations(workspace_id)`, submit each to the **shared** pool (one executor for the whole run, never one per workspace), collect results in submission order via a future→index map, and report progress through `on_progress`. A future raising outside `execute_visualization` is still recorded as a `BROKEN` `VizResult`, never dropped.
       Pre: task 10 complete (`Throttle`), task 8 complete (`execute_visualization`)
       AC: #1, #11

- [x] 12. Write `tests/test_execute.py` part 1 — statuses: a 20-row table yields `OK` with `row_count=20` and `attempts=1`; a zero-row table yields `EMPTY`, asserted explicitly as *not* `OK`; an `ApiException` with a canned 400 body yields `BROKEN` with `error` byte-identical to the body plus the correct `http_status`, `category` and `hint`; `KeyError('properties')` yields `SKIPPED`.
       Pre: task 11 complete (executor implemented), task 6 complete (programmable fake)
       AC: #1, #2, #3

- [x] 13. Write `tests/test_execute.py` part 2 — timing and resilience: a fake sleeping past `timeout_s=1` yields category `TIMEOUT` within roughly 1s of wall clock and the surrounding run continues; two 503s then a success yields `OK` with `attempts=3`; three 400s yields `BROKEN` with `attempts=1` and exactly one recorded SDK call.
       Pre: task 12 complete (status tests and fixtures in place)
       AC: #11

- [x] 14. Write `tests/test_execute.py` part 3 — concurrency: run 50 visualizations with `max_workers=4` and assert `FakeSdk`'s maximum simultaneous in-flight count never exceeded 4; a 429 response halves the budget, emits exactly one `ThrottleEvent` carrying `from_workers=4`/`to_workers=2`, and the run still completes with every visualization reported.
       Pre: task 13 complete (resilience tests), task 10 complete (`Throttle`)
       AC: #11

- [x] 15. Add `check_wdf_values(host, token, workspace_id) -> str | None` to `src/globalmart/preflight.py`: GET `/api/v1/entities/workspaces/{ws}/workspaceDataFilters` and `/workspaceDataFilterSettings` with a bearer token and `Accept: application/vnd.gooddata.api+json`, and return a remediation message when filters exist and zero values are set. Raw REST because the SDK has no coverage — note the gap in a comment per STEERING § Coding Standards. Never raises: any transport or non-200 outcome returns `None`, because a preflight must not block a run.
       Pre: FEAT-002 task 20 complete (`preflight.py` exists)
       AC: #10

- [x] 16. Extend `tests/test_preflight.py`: a stubbed transport reporting 2 filters and 0 settings returns a message naming the workspace and the count; 2 filters and 1 setting returns `None`; a 500 from either endpoint returns `None` without raising; a connection error returns `None` without raising.
       Pre: task 15 complete (`check_wdf_values`)
       AC: #10

- [x] 17. Create `tests/fixtures/mini_domains/` by running FEAT-004's splitter over `tests/fixtures/mini_globalmart/` with a 2-domain manifest: `mini-sales.json` and `mini-inventory.json`, each with a correctly pruned LDM. Commit a test asserting both regenerate byte-identically, so the fixtures cannot silently rot.
       Pre: FEAT-004 complete (splitter emits generated child JSON), FEAT-001 task 11 complete (`tests/fixtures/mini_globalmart/`)
       AC: #5, #6, #7

- [x] 18. Add the two negative fixtures beside them: `mini-sales-unpruned.json`, identical to `mini-sales.json` but carrying one extra LDM dataset unreachable from its retained metrics and visualizations, and `mini-inventory-gap.json`, identical to `mini-inventory.json` but with one dashboard removed so a coverage gap exists when paired with `mini-sales.json`. Both are hand-built fixtures with a README line stating they are intentionally invalid.
       Pre: task 17 complete (the valid fixtures define what "invalid" deviates from)
       AC: #6, #7

- [x] 19. Create `src/globalmart/expect.py` with the count axis: `expected_parent_counts(tree_path) -> ObjectCounts` (via `read_tree` + `count_objects`), `expected_child_counts(json_path) -> ObjectCounts`, the `CountMismatch` dataclass (`workspace_id`, `object_type`, `expected`, `actual`), and `compare_counts(workspace_id, expected, actual) -> list[CountMismatch]` covering datasets, metrics, visualizations, dashboards, date instances and the AI-context object types. Each workspace is compared against its own expectation — never a child against the parent's.
       Pre: FEAT-001 task 7 complete (`count_objects`, `ObjectCounts`), FEAT-001 task 9 complete (`read_tree`), task 17 complete (child fixtures to count)
       AC: #5

- [x] 20. Add `check_coverage(parent_model, children) -> CoverageReport` to `expect.py`: collect every parent dashboard id and visualization id, union the ids present across the children, and populate `parent_dashboards`, `parent_visualizations`, `covered_*`, `missing_dashboard_ids`, `missing_visualization_ids`, `multi_domain_visualization_ids` (informational — a shared visualization is legal) and `passed`. Reads the committed artifacts only; it must not import anything from FEAT-004's splitter.
       Pre: task 19 complete (`expect.py` exists), task 18 complete (the coverage-gap fixture)
       AC: #6

- [x] 21. Add `check_pruning(parent_model, children) -> list[PruningViolation]` to `expect.py`: for each child, compute the dataset closure reachable from that child's retained metrics and visualizations (metric → MAQL references → metric → dataset, and visualization → attribute/measure → dataset, plus join ancestors), flag every LDM dataset outside it as `reason="unreachable"`, and flag `reason="dataset_count_not_reduced"` when the child's dataset count is not strictly less than the parent's. Written independently of FEAT-004's closure code — the point is a second opinion on the artifact, not a re-run of the generator.
       Pre: task 20 complete (`check_coverage` established the artifact-reading pattern), task 18 complete (`mini-sales-unpruned.json`)
       AC: #7

- [x] 22. Write `tests/test_expect.py`: `expected_parent_counts` on `mini_globalmart` equals `count_objects` on the same tree; `compare_counts` is empty on equal counts and yields exactly one `metrics` mismatch when three metrics are missing; comparing `mini-sales.json` against the *parent's* expectation produces mismatches (the guard that each workspace gets its own expectation); `check_coverage` passes on the valid pair and fails naming only the removed dashboard id on the gap pair; `check_pruning` is empty on `mini-sales.json` and returns exactly one `unreachable` violation naming the extra dataset on `mini-sales-unpruned.json`; a child whose dataset count equals the parent's yields `dataset_count_not_reduced`.
       Pre: task 21 complete (all three check functions)
       AC: #5, #6, #7

- [x] 23. Create `src/globalmart/report.py` with the `VerificationRun` and `WorkspaceVerification` dataclasses as specified in the breakdown's Data Model (including `schema_version: int = 1` as the first field, `repo_commit`, `options`, `failure_reasons`), plus `ThrottleEvent` imported from `execute.py`. Define them here rather than in `verify.py` so `report.py` can be loaded and tested without importing the SDK.
       Pre: task 11 complete (`VizResult` final), task 21 complete (`CoverageReport`, `PruningViolation` final)
       AC: #4

- [x] 24. Implement `render_json(run) -> dict` (via `dataclasses.asdict`, `schema_version` first), `load_run(path) -> VerificationRun` (re-hydrating enums and nested dataclasses), and `write_reports(run, output_dir) -> tuple[Path, Path]` writing `verification_result.json` and `verification_report.md`. Add `reports/` to `.gitignore`.
       Pre: task 23 complete (the dataclasses)
       AC: #4

- [x] 25. Implement `render_markdown(run) -> str` in `report.py`, broken-first in the predecessor's shape: header with target, host, org, `repo_commit`, `generated_at`, effective options, and the fixed "what this report cannot tell you" paragraph (wrong-but-computable numbers, valid-but-empty results, no dashboard rendering, AI context counted not tested); an aggregate table over the 13 workspaces; then per workspace the WDF warning, count mismatches, the broken list with workspace id, object id, title, HTTP status, category, hint and verbatim error, the empty list, and a collapsed OK list. It must import nothing from the SDK.
       Pre: task 24 complete (`render_json`, `load_run`)
       AC: #2, #4

- [x] 26. Add `tests/fixtures/verification/run_pass.json` and `run_fail.json` — two committed `VerificationRun` payloads (13 workspaces each; the second carrying broken, empty and skipped visualizations, a count mismatch, a coverage gap and a pruning violation) hand-built to exercise every branch of the renderer.
       Pre: task 25 complete (the renderer fixes what the payloads must contain)
       AC: #4

- [x] 27. Write `tests/test_report.py`: `load_run(write_reports(run)[0]) == run` round-trips for both fixtures; `render_markdown(run_fail)` lists broken visualizations before OK ones, names every broken object id, and contains each broken viz's error byte-for-byte; the "what this report cannot tell you" paragraph appears in both rendered reports; the Markdown is regenerable from the JSON alone with no SDK import (asserted by patching `gooddata_sdk` out of `sys.modules`); `schema_version` is `1` and is the JSON's first key.
       Pre: task 26 complete (both run fixtures)
       AC: #4

- [x] 28. Create `src/globalmart/verify.py` with `VerifyOptions` (`max_workers: int = 8`, `viz_timeout: int = 180`, `max_retries: int = 2`, `fail_on_empty: bool = False`, `only_workspaces: list[str] | None = None`, `list_only: bool = False`) and `resolve_workspace_set(profile, domains) -> list[tuple[str, str, str | None]]` returning `(workspace_id, role, domain_key)` for the parent plus each domain in `domains.yaml`, with `profile.workspace_id_prefix` applied via FEAT-002's `resolved_workspace_id`. The set comes from the repo; the org's contents never add to or remove from it.
       Pre: FEAT-003 complete (`domains.yaml` with the 12 domains and their child ids), FEAT-002 task 25 complete (`resolved_workspace_id`)
       AC: #1, #12

- [x] 29. Implement `verify_workspace(sdk, profile, workspace_id, role, domain_key, *, expected, pool, throttle, options) -> WorkspaceVerification`: WDF preflight first, then `get_declarative_workspace` for the live layout, `count_objects` + `compare_counts`, then `execute_workspace`. Set `present=False` (and skip execution) when the workspace is absent from the org, compute `viz_ok`/`viz_empty`/`viz_broken`/`viz_skipped`, `empty_ratio`, and `systemic_category` (set only when every failure shares one category — one finding, not N).
       Pre: task 28 complete (`VerifyOptions`, workspace set), tasks 11, 15, 19 complete (executor, WDF preflight, counts)
       AC: #1, #5, #10

- [x] 30. Implement `verify_target(sdk, profile, domains, *, options) -> VerificationRun`: create one shared `ThreadPoolExecutor` and one `Throttle` for the whole run, iterate the 13 workspaces sequentially, call `check_coverage` and `check_pruning` once over the committed artifacts, capture `repo_commit` from `git rev-parse HEAD` (falling back to `"unknown"`), and compute `passed` plus one human sentence in `failure_reasons` per reason — broken visualizations, an absent workspace, a count mismatch, a coverage gap, a pruning violation, and empties only under `fail_on_empty`.
       Pre: task 29 complete (`verify_workspace`), tasks 20, 21 complete (coverage and pruning), task 23 complete (`VerificationRun`)
       AC: #1, #3, #5, #6, #7

- [x] 31. Write `tests/test_verify.py` part 1 — the happy path and the workspace-set guard: a `FakeSdk` serving 13 workspaces with passing executions yields `passed=True`, `failure_reasons == []` and exactly 13 `WorkspaceVerification` entries; a fake missing `globalmart-inventory` still yields 13 entries with that one `present=False` and a failure reason naming it; a fake with an extra unexpected workspace still yields exactly 13.
       Pre: task 30 complete (`verify_target`), task 5 complete (`FakeSdk.list_workspaces`)
       AC: #1, #12

- [x] 32. Write `tests/test_verify.py` part 2 — failure semantics: one broken visualization flips `passed` to `False`, adds exactly one `failure_reason`, and leaves the other twelve workspaces green; an all-empty workspace passes with `empty_ratio > 0.5` recorded but fails under `fail_on_empty=True`; `systemic_category` is set when every failure shares a category and `None` when they differ; the WDF warning is produced before any `for_visualization` call, asserted by call ordering on the fake.
       Pre: task 31 complete (happy-path harness)
       AC: #1, #3, #10

- [x] 33. Add `dict_diff(a: dict, b: dict) -> list[str]` to the existing `src/globalmart/compare.py`: a stable-sorted, path-wise list of `path: a_value != b_value` lines over two already-masked dicts, including keys present in one side only. Do not touch `mask_parameters` — FEAT-002's tests must pass unmodified.
       Pre: FEAT-002 task 15 complete (`mask_parameters`), FEAT-002 task 16 complete (`tests/test_compare.py` to keep green)
       AC: #9

- [x] 34. Create `src/globalmart/equivalence.py` with the `EquivalenceReport` dataclass (`target_a`, `target_b`, `workspace_id`, `digest_a`, `digest_b`, `equivalent`, `differing_paths`) and `compare_orgs(sdk_a, profile_a, sdk_b, profile_b, workspace_id) -> EquivalenceReport`: fetch both layouts with `get_declarative_workspace`, digest each with `model_digest`, mask each with `mask_parameters` against its own profile, and diff the masked dicts with `dict_diff`.
       Pre: task 33 complete (`dict_diff`), FEAT-002 task 15 complete (`mask_parameters`, `model_digest`)
       AC: #9

- [x] 35. Write `tests/test_equivalence.py`: two `FakeSdk`s serving the same fixture tree resolved for the `demo-cloud` and `local-inference` profiles yield `equivalent=True` with `differing_paths == []` while `digest_a != digest_b` — proving the masking is load-bearing and the assertion is not vacuous; changing one metric title in org B yields `equivalent=False` with exactly one differing path naming that metric.
       Pre: task 34 complete (`compare_orgs`), FEAT-002 task 33 complete (`tests/fixtures/published_layouts/`)
       AC: #9

- [x] 36. Extend `src/globalmart/cli.py` with `globalmart verify --target <profile> [--workspace <id> ...] [--max-workers 8] [--viz-timeout 180] [--max-retries 2] [--fail-on-empty] [--output-dir reports] [--list-only]` and `globalmart verify equivalence --target-a <a> --target-b <b> [--workspace-id globalmart]`. `verify` is read-only and must expose **no** `--apply` and **no** `--dry-run`; `--list-only` names every object without executing it. Read defaults from an optional `verify:` block on the profile, with CLI flags taking precedence. Exit 0 on pass, 1 on a verification failure, 2 on a configuration or credential error.
       Pre: task 30 complete (`verify_target`), task 34 complete (`compare_orgs`), FEAT-002 task 30 complete (`cli.py` command groups)
       AC: #1, #4, #9

- [x] 37. Add the optional `verify:` block (`max_workers`, `viz_timeout`, `fail_on_empty`) to each profile in `config/targets.yaml` and to `TargetProfile` as a `verify: VerifyOptions | None = None` field, so a slow local-inference host can be gentler than demo cloud without flags on every invocation. Extend `tests/test_config.py` (do not add a module) to assert the block parses, is optional, and is overridden by explicit CLI values.
       Pre: task 36 complete (the flag surface fixes the field names), FEAT-002 task 6 complete (`TargetProfile`)
       AC: #11

- [x] 38. Extend `tests/test_cli.py`: `verify` parses without `--apply` and without `--dry-run` (asserted against the parser, so the STEERING CLI convention cannot rot); `--list-only` records zero `for_visualization` calls on `FakeSdk` while still listing every object; a passing run exits 0 and writes both report files under `--output-dir`; a run with one broken visualization exits 1; a profile missing a required key exits 2 with zero SDK calls.
       Pre: task 36 complete (subcommands wired), task 24 complete (`write_reports`)
       AC: #1, #4

- [x] 39. Create `src/globalmart/rebuild.py` with `StepStatus` (`StrEnum`: `OK`, `FAILED`, `SKIPPED`, `PLANNED`), the `RebuildStep` dataclass (`name`, `cli_equivalent`, `status`, `duration_s`, `detail`, `error`) and the `RebuildReport` dataclass (`target`, `applied`, `started_from_empty_org`, `allow_existing`, `steps`, `passed`), plus `probe_empty_org(sdk, profile) -> bool` using `sdk.catalog_workspace.list_workspaces()` and `RebuildAbortedError`.
       Pre: task 23 complete (report dataclass conventions), FEAT-002 task 6 complete (`GlobalmartError`)
       AC: #8

- [x] 40. Implement `cold_rebuild(profile, domains, *, apply: bool = False, allow_existing: bool = False, options) -> RebuildReport` building the 17-step chain — probe, generate-data, load-warehouse, publish-parent, generate-domains, 12 × publish-child, verify — by **in-process function call**, not subprocess. Thread `apply` into every writing step rather than re-gating here (ADR 002); populate `cli_equivalent` on every step so a human can reproduce any one by hand; abort with `RebuildAbortedError` when the org already holds the parent workspace and `allow_existing` is false; short-circuit the remaining steps as `SKIPPED` on the first failure, recording the exception text.
       Pre: task 39 complete (step dataclasses, `probe_empty_org`), task 30 complete (`verify_target`), FEAT-002 task 26 complete (`publish_workspace`), FEAT-004 complete (`generate_domains`), FEAT-005 complete (`generate_data`, `load_warehouse`)
       AC: #8

- [x] 41. Write `tests/test_rebuild.py` part 1 — ordering and the safe default: a full `cold_rebuild(..., apply=True)` against `FakeSdk` records exactly 17 steps in the documented order, all `OK`; `cold_rebuild(..., apply=False)` records **zero** write calls on the fake (no datasource upsert, no workspace upsert, no PUT, no warehouse load) while still producing 17 `PLANNED` steps each with a non-empty `cli_equivalent`; a separate test reads the signature and asserts the default value of `apply` is `False`.
       Pre: task 40 complete (`cold_rebuild`)
       AC: #8

- [x] 42. Write `tests/test_rebuild.py` part 2 — the empty-org guard and failure propagation: a fake whose org already holds `globalmart` raises `RebuildAbortedError`, and with `allow_existing=True` proceeds with `started_from_empty_org=False`; a fake failing the parent publish leaves every subsequent step `SKIPPED`, carries the exception text on the failed step, and yields `passed=False`.
       Pre: task 41 complete (ordering tests)
       AC: #8

- [x] 43. Add `globalmart rebuild --target <profile> [--apply] [--allow-existing] [--skip-data] [--output-dir reports]` to `cli.py`, including the step-plan printer for the no-`--apply` rehearsal (one line per step: name, status, `cli_equivalent`) headed with the literal `REHEARSAL — no writes. Re-run with --apply to rebuild.`, matching FEAT-002's rehearsal wording. On `--apply` it writes both the `RebuildReport` and the final `VerificationRun` into `--output-dir` and exits 1 if either failed.
       Pre: task 40 complete (`cold_rebuild`), task 36 complete (the `verify` command it ends with), task 24 complete (`write_reports`)
       AC: #8

- [x] 44. Extend `tests/test_cli.py` for `rebuild`: without `--apply` it exits 0, prints the rehearsal header and 17 plan lines, and records zero writes on `FakeSdk`; with `--apply` against an org already holding `globalmart` it exits non-zero naming `--allow-existing`; with `--apply` on a clean fake it writes both report files. Extend `tests/test_no_hardcoded_identifiers.py` to cover the new modules and to assert that no `globalmart-<domain>` literal appears in `verify.py` or `rebuild.py` — the workspace set must come from `domains.yaml`.
       Pre: task 43 complete (`rebuild` subcommand), FEAT-002 task 35 complete (`tests/test_no_hardcoded_identifiers.py`)
       AC: #8, #12

- [x] 45. Write `docs/verification.md`: what each of the four axes asserts (execution, counts, coverage + pruning, cross-org equivalence); the explicit list of what the harness provably cannot catch (semantically wrong numbers, valid empty results, dashboard rendering, AI-context behaviour); how to read `verification_result.json` field by field with its `schema_version` contract; the exit-code contract (0/1/2); and the cold-rebuild runbook for a fresh org — the credentials needed, the single command, and what a passing run proves about goal-01.
       Pre: tasks 30, 40, 43 complete (the four axes, the step chain and the final CLI surface all fixed)
       AC: #4, #8

- [x] 46. **Requires explicit user approval to run against a live host.** Run `globalmart verify --target demo-cloud --list-only` and confirm it enumerates 13 workspaces and roughly 384 visualization objects in the parent without executing anything; then run the full `globalmart verify --target demo-cloud` and read `verification_report.md`: confirm the count assertions pass per workspace against each workspace's own expectation, the coverage and pruning sections are clean, and every broken visualization is named with its id and server error.
       Pre: tasks 38, 44 complete (offline suite green); credentials for `petertomko.demo.cloud`; FEAT-002 and FEAT-004 already published there
       AC: #1, #2, #4, #5, #6, #7, #10

- [x] 47. **Requires explicit user approval to run against a live host.** Run `globalmart verify equivalence --target-a demo-cloud --target-b local-inference --workspace-id globalmart` and confirm `equivalent=True` with an empty `differing_paths`; investigate and record any path that differs outside host, org, datasource id and schema, as it is a portability-contract violation rather than a harness bug.
       Pre: task 46 complete (single-org verification accepted), FEAT-002 task 39 complete (both orgs published from the same repo state)
       AC: #9

- [x] 48. **Requires explicit user approval to run against a live host, and it writes to that org.** Run `globalmart rebuild --target fresh-org` (rehearsal) and review the 17-step plan; then run `globalmart rebuild --target fresh-org --apply` against a genuinely empty org, confirming `started_from_empty_org=True`, every step `OK`, and a final `VerificationRun` with `passed=True` and zero broken visualizations across all 13 workspaces. Keep that `verification_result.json` — it is the evidence for goal-01's measurable outcome.
       Pre: task 47 complete (equivalence confirmed); an empty GoodData org, its write credentials and its warehouse secret; FEAT-005 data generation runnable
       AC: #1, #3, #5, #6, #7, #8
