## Technical Breakdown — FEAT-006: Rebuild verification: cold-rebuild smoke test that executes every visualization in the parent and every domain workspace and reports failures

> **Continuity with FEAT-001/002.** No new package, no new CLI, no new config file. This extends `src/globalmart/` (console script `globalmart`) and reuses `TargetProfile` / `load_profile()` / `GlobalmartError` from `config.py`, `make_sdk()` from `sdk_client.py`, `read_tree()` from `layout_io.py`, `count_objects()` / `ObjectCounts` from `counts.py`, `mask_parameters()` / `model_digest()` from `compare.py`, `publish_workspace()` / `PublishResult` from `publish.py`, and the `FakeSdk` double from `tests/conftest.py`. The workspace set comes from FEAT-003's `domains.yaml`, never from what the org happens to contain.

> **The single claim this feature exists to prove.** goal-01 says a clean clone plus credentials for an empty org rebuilds the parent and all 12 children with *every visualization executing successfully and no manual step*. Four things have to be true for that sentence to hold, and each gets its own axis here: executions succeed (`execute.py`), the right objects arrived (`expect.py` counts), the split lost nothing (`expect.py` coverage + pruning), and the result is org-independent (`equivalence`, on FEAT-002's `mask_parameters`). `rebuild.py` is what removes "no manual step" from the honour system. Everything else is reporting.

> **What this harness cannot prove, stated once so it is not implied anywhere else.** A visualization that computes and returns wrong numbers passes. An empty result is surfaced but not judged. Dashboard rendering, drills and filter contexts are never exercised. AI context is counted, never behaviourally tested. These are limits of the approach, not gaps in the implementation, and `report.py` prints them in the header of every Markdown report.

---

### Components

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|
| `src/globalmart/classify.py` | The failure taxonomy, ported from the predecessor's `classifier.py` and made a `StrEnum` instead of a `Literal`. `FailureCategory` with 13 members (the predecessor's 11 plus `EMPTY_RESULT` and `RATE_LIMITED`), `_HINTS: dict[FailureCategory, str]` carrying one remediation hint each, `classify(error: str, status: int | None) -> Failure` matching in documented priority order (first match wins), and `extract_status(exc: BaseException) -> int | None` using the predecessor's regex over `HTTP nnn` / `status: nnn` / `(nnn)` / `Reason: nnn`. `is_retryable(category) -> bool` returns true only for `TRANSIENT_5XX` and `RATE_LIMITED`. Pure — no network, no SDK import — so the whole taxonomy is unit-testable with canned strings. | New (port) | S |
| `src/globalmart/execute.py` | The core. `execute_visualization(sdk, workspace_id, viz, *, timeout_s, max_retries, throttle) -> VizResult` runs `sdk.tables.for_visualization(workspace_id, viz, always_two_dimensional=True)` inside an inner daemon thread joined with a hard timeout (the predecessor's pattern — `ThreadPoolExecutor` cannot cancel an in-flight task), retries only retryable categories with exponential backoff, and derives `row_count` from the returned table so `EMPTY` can be distinguished from `OK`. `execute_workspace(sdk, workspace_id, *, pool, ...) -> list[VizResult]` lists objects with `sdk.visualizations.get_visualizations(workspace_id)` and submits each to a **shared** executor. `Throttle` is a small class holding the live concurrency budget as a `threading.Semaphore`; on a 429 or a burst of 5xx it halves the budget for the remainder of the workspace and records a `ThrottleEvent`. A non-insight type raising `KeyError('properties')` becomes `SKIPPED` with category `UNSUPPORTED_TYPE`, never `BROKEN`. | New | L |
| `src/globalmart/preflight.py` | Extended with `check_wdf_values(host, token, workspace_id) -> str | None` — the predecessor's highest-value check, kept verbatim in behaviour: GET `/api/v1/entities/workspaces/{ws}/workspaceDataFilters` and `.../workspaceDataFilterSettings` (raw REST; the SDK has no coverage — noted in a comment per STEERING § Coding Standards), and return a remediation message when there are filters defined and zero values set. Never raises; a preflight must not block a run. FEAT-001 defaults to `WdfPolicy.DROP`, so in a repo-built org this must always return `None` — the check exists to prove that, and a non-`None` result is a workspace-level warning above the per-object list. | Existing — modified | S |
| `src/globalmart/expect.py` | Repo-derived expectations, all computed from committed artifacts and none from a live org. `expected_parent_counts(tree_path) -> ObjectCounts` (`read_tree` + `count_objects`), `expected_child_counts(json_path) -> ObjectCounts` per generated child, `compare_counts(expected, actual) -> list[CountMismatch]`. `check_coverage(parent_model, children) -> CoverageReport` — every parent dashboard id and visualization id must appear in at least one child. `check_pruning(parent_model, children) -> list[PruningViolation]` — for each child, compute the reachable dataset closure from its retained metrics and visualizations and flag any LDM dataset outside it, plus assert `len(child.datasets) < len(parent.datasets)`. Reads FEAT-004's *output*, never its internals. | New | M |
| `src/globalmart/verify.py` | Orchestration of the read-only axis. `verify_target(sdk, profile, domains, *, options) -> VerificationRun` resolves the workspace set as `[parent] + [child for each domain in domains.yaml]` — **13, from the repo, not from the org** — then per workspace: WDF preflight → fetch the live layout via `get_declarative_workspace` → `count_objects` → `compare_counts` against that workspace's own expectation → execute every visualization on the shared pool → assemble a `WorkspaceVerification`. Afterwards it runs `check_coverage` and `check_pruning` once over the committed artifacts, computes `passed` and `failure_reasons`, and returns. A workspace the repo expects and the org lacks is a `WorkspaceVerification` with `present=False` and is a failure, not a skip. | New | M |
| `src/globalmart/equivalence.py` | `compare_orgs(sdk_a, profile_a, sdk_b, profile_b, workspace_id) -> EquivalenceReport` — fetch both layouts with `get_declarative_workspace`, run each through FEAT-002's `compare.mask_parameters()`, digest both with `model_digest()`, and diff the masked dicts producing `differing_paths`. `compare.py` itself gains only `dict_diff(a: dict, b: dict) -> list[str]` (a path-wise diff over already-masked dicts); all the masking logic stays where FEAT-002 put it. | New (+ a one-function addition to existing `compare.py`) | S |
| `src/globalmart/rebuild.py` | The "no manual step" proof. `RebuildStep` describes one link in the chain and `cold_rebuild(profile, *, apply, allow_existing, options) -> RebuildReport` executes them in order by **in-process function call, not subprocess**: `probe_empty_org` → `generate_data` (FEAT-005) → `load_warehouse` (FEAT-005) → `publish parent` (FEAT-002 `publish_workspace`) → `generate_domains` (FEAT-004) → `publish` each of the 12 children (FEAT-002 `publish_workspace`, 12 steps) → `verify_target` (this feature). `apply` is threaded into every step rather than re-gated here, per ADR 002; without it the chain is a rehearsal that prints the step plan and its CLI equivalent per step. `probe_empty_org` uses `sdk.catalog_workspace.list_workspaces()` and sets `started_from_empty_org`; finding an existing `globalmart` aborts unless `--allow-existing` is passed, so the cold-rebuild claim cannot be made by a warm run. A failed step short-circuits the rest and is reported with its exception. | New | M |
| `src/globalmart/report.py` | Both output formats, and the only module that knows about presentation. `render_json(run) -> dict` — `dataclasses.asdict` with `schema_version` first. `render_markdown(run) -> str` — the predecessor's broken-first shape: header (host, org, target, commit, generated-at, and the fixed "what this report cannot tell you" paragraph), an aggregate table over the 13 workspaces, then per workspace the WDF warning, the count mismatches, the broken list with id/title/status/category/hint/verbatim error, the empty list, and a collapsed OK list. `load_run(path) -> VerificationRun` re-hydrates a stored JSON so `render_markdown` can regenerate an old report without a host. `write_reports(run, output_dir) -> tuple[Path, Path]` writes `verification_result.json` and `verification_report.md`. | New | M |
| `src/globalmart/cli.py` | Adds `globalmart verify --target <profile> [--workspace <id> ...] [--max-workers 8] [--viz-timeout 180] [--max-retries 2] [--fail-on-empty] [--output-dir reports] [--list-only]`, `globalmart verify equivalence --target-a <a> --target-b <b> [--workspace-id globalmart]`, and `globalmart rebuild --target <profile> [--apply] [--allow-existing] [--skip-data] [--output-dir reports]`. `verify` is read-only and therefore takes **no** `--apply` and no `--dry-run` (`--list-only` names objects without executing, mirroring the predecessor's `--dry-run` without colliding with the CLI convention in STEERING). Exit codes: 0 pass, 1 verification failure, 2 configuration/credential error. | Existing — modified | S |
| `config/targets.yaml` | Optional per-profile `verify:` block with `max_workers`, `viz_timeout`, `fail_on_empty` so a slow local-inference host can be gentler than demo cloud without flags on every invocation. CLI flags win over the profile block. | Existing — modified | S |
| `.gitignore` | `reports/` added. | Existing — modified | S |
| `tests/fixtures/verification/` | `run_pass.json` and `run_fail.json` — two committed `VerificationRun` payloads used to test `render_markdown` and `load_run` without executing anything; `errors/*.txt` — ~20 canned server error bodies, one per taxonomy category plus the ambiguous ones, for `test_classify.py`. | New | S |
| `tests/fixtures/mini_domains/` | A 2-domain miniature of FEAT-004's output (`mini-sales.json`, `mini-inventory.json`) derived from `mini_globalmart`, with a deliberately over-broad third variant `mini-sales-unpruned.json` carrying one unreachable dataset, so coverage and pruning both have a positive and a negative case offline. | New | M |
| `tests/` (7 new modules, see Test Strategy) | `test_classify.py`, `test_execute.py`, `test_expect.py`, `test_verify.py`, `test_equivalence.py`, `test_rebuild.py`, `test_report.py`. | New | L |
| `docs/verification.md` | One page: what the four axes assert, what the harness provably cannot catch, how to read `verification_result.json`, the exit-code contract, and the cold-rebuild runbook for a fresh org. | New | S |

---

### Data Model

Everything is a frozen-where-possible dataclass in the module that owns it, serialized by `dataclasses.asdict` — the predecessor's approach, which is what makes the JSON and the Markdown two renderings of one object rather than two code paths.

**`FailureCategory`** (`classify.py`, `StrEnum`): `WDF_NO_VALUE`, `PROTECTED`, `INVALID_IDENTIFIER`, `LDM_MAPPING`, `DATA_LIMIT`, `CALC_ERROR`, `TOO_LARGE_TIMEOUT`, `TRANSIENT_5XX`, `RATE_LIMITED`, `UNSUPPORTED_TYPE`, `TIMEOUT`, `EMPTY_RESULT`, `UNKNOWN`.

**`Failure`** (`classify.py`, `NamedTuple`): `category: FailureCategory`, `hint: str`.

**`ExecStatus`** (`execute.py`, `StrEnum`): `OK`, `EMPTY`, `BROKEN`, `SKIPPED`.

**`VizResult`** (`execute.py`, dataclass):

| Field | Type |
|---|---|
| `workspace_id` | `str` |
| `viz_id` | `str` |
| `title` | `str` |
| `status` | `ExecStatus` |
| `duration_ms` | `int` |
| `attempts` | `int` (>1 means it was retried; a pass on attempt 3 is never silently green) |
| `row_count` | `int \| None` (`None` when the execution did not return a table) |
| `column_count` | `int \| None` |
| `error` | `str \| None` (the server's body verbatim, untruncated in JSON) |
| `http_status` | `int \| None` |
| `category` | `FailureCategory \| None` |
| `hint` | `str \| None` |

**`ThrottleEvent`** (`execute.py`, dataclass): `workspace_id: str`, `at: str` (UTC ISO-8601), `from_workers: int`, `to_workers: int`, `trigger: str` (`"429"` or `"5xx-burst"`).

**`CountMismatch`** (`expect.py`, dataclass): `workspace_id: str`, `object_type: str` (`"datasets"`, `"metrics"`, `"visualizations"`, `"dashboards"`, `"date_instances"`, `"memory_items"`, `"agent_personalities"`, `"ai_knowledge"`), `expected: int`, `actual: int`.

**`CoverageReport`** (`expect.py`, dataclass): `parent_dashboards: int`, `parent_visualizations: int`, `covered_dashboards: int`, `covered_visualizations: int`, `missing_dashboard_ids: list[str]`, `missing_visualization_ids: list[str]`, `multi_domain_visualization_ids: list[str]` (informational — a shared visualization is legal), `passed: bool`.

**`PruningViolation`** (`expect.py`, dataclass): `workspace_id: str`, `dataset_id: str`, `reason: str` (`"unreachable"` or `"dataset_count_not_reduced"`).

**`WorkspaceVerification`** (`verify.py`, dataclass):

| Field | Type |
|---|---|
| `workspace_id` | `str` (e.g. `globalmart`, `globalmart-sales`) |
| `role` | `str` (`"parent"` or `"domain"`) |
| `domain_key` | `str \| None` (snake_case key from `domains.yaml`; `None` for the parent) |
| `present` | `bool` (repo expects it; is it in the org?) |
| `wdf_warning` | `str \| None` |
| `counts_expected` | `ObjectCounts` (FEAT-001's, from the repo artifact for **this** workspace) |
| `counts_actual` | `ObjectCounts` (from the live layout) |
| `count_mismatches` | `list[CountMismatch]` |
| `viz_total` / `viz_ok` / `viz_empty` / `viz_broken` / `viz_skipped` | `int` |
| `systemic_category` | `FailureCategory \| None` (set when 100% of failures share one category — one finding, not N) |
| `empty_ratio` | `float` (warning emitted above 0.5) |
| `throttle_events` | `list[ThrottleEvent]` |
| `duration_s` | `float` |
| `visualizations` | `list[VizResult]` |

**`EquivalenceReport`** (`equivalence.py`, dataclass): `target_a: str`, `target_b: str`, `workspace_id: str`, `digest_a: str`, `digest_b: str`, `equivalent: bool`, `differing_paths: list[str]`.

**`StepStatus`** (`rebuild.py`, `StrEnum`): `OK`, `FAILED`, `SKIPPED`, `PLANNED`.

**`RebuildStep`** (`rebuild.py`, dataclass): `name: str` (e.g. `"publish-child:globalmart-sales"`), `cli_equivalent: str` (the command a human would run to reproduce this step alone), `status: StepStatus`, `duration_s: float`, `detail: str` (e.g. `PublishResult.digest_after`, rows loaded, objects generated), `error: str | None`.

**`RebuildReport`** (`rebuild.py`, dataclass): `target: str`, `applied: bool`, `started_from_empty_org: bool`, `allow_existing: bool`, `steps: list[RebuildStep]` (17 on a full run: probe, generate-data, load-warehouse, publish-parent, generate-domains, 12 × publish-child, verify), `passed: bool`.

**`VerificationRun`** (`verify.py`, dataclass) — the top-level serialized object, the CI gate and the historical record:

| Field | Type |
|---|---|
| `schema_version` | `int` (literal `1`; bumped on any breaking field change) |
| `generated_at` | `str` (UTC ISO-8601) |
| `target` | `str` (profile name) |
| `host` | `str` |
| `organization_id` | `str` |
| `repo_commit` | `str` (`git rev-parse HEAD`, or `"unknown"` outside a work tree) |
| `options` | `dict[str, Any]` (effective max_workers, viz_timeout, max_retries, fail_on_empty — so a run is reproducible from its own output) |
| `workspaces` | `list[WorkspaceVerification]` (asserted to be exactly 13) |
| `coverage` | `CoverageReport` |
| `pruning_violations` | `list[PruningViolation]` |
| `equivalence` | `EquivalenceReport \| None` |
| `rebuild` | `RebuildReport \| None` |
| `total_viz` / `total_ok` / `total_empty` / `total_broken` / `total_skipped` | `int` |
| `duration_s` | `float` |
| `passed` | `bool` |
| `failure_reasons` | `list[str]` (one human sentence per reason the run failed; empty iff `passed`) |

**Exceptions** (subclasses of FEAT-002's `GlobalmartError`): `VerificationFailedError` (raised by the CLI layer to set exit 1), `WorkspaceMissingError`, `RebuildAbortedError` (non-empty org without `--allow-existing`, or a failed step).

No database and no warehouse schema. The only persisted state is `reports/` (gitignored), which mirrors FEAT-002's treatment of `backups/`.

---

### Integration Points

- **`gooddata-python-sdk`** — four call sites beyond FEAT-001/002's:
  - `sdk.visualizations.get_visualizations(workspace_id)` — the object list to execute. Returns visualization objects, not ids, and they are passed straight to the executor.
  - `sdk.tables.for_visualization(workspace_id, viz, always_two_dimensional=True)` — **the execution**, and the only reliable breakage detector; no declarative property marks a visualization as broken. `always_two_dimensional=True` matches the predecessor so headline/one-dimensional insights do not take a different code path.
  - `sdk.catalog_workspace.list_workspaces()` — `rebuild`'s empty-org probe, and `verify`'s check that every workspace `domains.yaml` expects actually exists.
  - `sdk.catalog_workspace.get_declarative_workspace(workspace_id=...)` — the live layout for counts and for equivalence. The org-agnostic read path FEAT-001 established; never `load_declarative_workspace`.
- **Raw REST** — the two `workspaceDataFilter` endpoints only, for the WDF preflight. The SDK has no coverage, and the gap is noted in a comment per STEERING § Coding Standards. Both are GETs, both are wrapped so a failure returns `None` rather than blocking the run.
- **FEAT-001** — `read_tree()`, `count_objects()`, `ObjectCounts`, the committed parent tree as the parent's count expectation.
- **FEAT-002** — `TargetProfile`/`load_profile()`, `make_sdk()`, `publish_workspace()`/`PublishResult` (called by `rebuild`), `compare.mask_parameters()`/`model_digest()` (the equivalence axis), `GlobalmartError`, and `FakeSdk` from `tests/conftest.py`, extended here rather than replaced.
- **FEAT-003** — `domains.yaml` is the **authoritative** source of the 13-workspace set: the 12 domain keys, their labels and their child workspace ids. Deriving the set from the org instead would let a missing workspace pass as "nothing to verify", which is the failure mode the `present` flag exists to catch.
- **FEAT-004** — consumes `generated/workspaces/globalmart-<domain>.json` as artifacts and calls its `generate_domains()` from `rebuild`. The coverage and pruning checks are deliberately written against the files, so they hold even if FEAT-004's internals change.
- **FEAT-005** — `rebuild` calls its `generate_data()` and `load_warehouse()`. Without loaded rows the run is not "failed" in an interesting way: it is uniformly `EMPTY`, which is exactly the signal `empty_ratio` and the >50% warning exist to give.
- **CI** — the offline suite runs on every PR and covers the whole harness against `FakeSdk`. **No CI job verifies against a live org**, per STEERING § AI Behavior; live runs are user-initiated, and the JSON is shaped so a future CI gate is a file read, not a redesign.
- **Environment** — read-only credentials suffice for `verify` and `verify equivalence`. `rebuild` additionally needs write credentials and the warehouse secret, and inherits FEAT-002's `--apply` gate on every writing step.

---

### Test Strategy

Everything runs offline, `uv run pytest tests/ -x -q`, against committed fixtures and the `FakeSdk` from FEAT-002's `tests/conftest.py` — extended here with `visualizations.get_visualizations()` returning a configurable object list, `tables.for_visualization()` programmable per viz id (return a table, raise an `ApiException` with a canned body, return an empty table, or sleep past the timeout), and `catalog_workspace.list_workspaces()`. Testing a tester has one trap — a harness that reports green because it executed nothing — so several tests assert *call counts on the fake*, not just the summary.

**Unit — `tests/test_classify.py`** (the cheapest, highest-coverage module)
- One parametrized case per taxonomy category, driven by `tests/fixtures/verification/errors/*.txt`, asserting the category and that the hint is non-empty.
- Priority order is pinned: an error matching both the WDF signal and the calc-error signal classifies as `WDF_NO_VALUE`, because a workspace-wide cause must win over a per-object one.
- `extract_status` recovers `500` from `"HTTP 500"`, `"status: 500"`, `"(500)"` and `"Reason: 500"`, and returns `None` from a string carrying no status.
- `is_retryable` is true for exactly `TRANSIENT_5XX` and `RATE_LIMITED` and false for the other eleven — so a deterministic defect can never be retried into a pass.
- A bare `KeyError('properties')` classifies `UNSUPPORTED_TYPE`, the predecessor's real-world case.

**Unit — `tests/test_execute.py`**
- Happy path: a `FakeSdk` returning a 20-row table yields `status=OK`, `row_count=20`, `attempts=1`.
- A zero-row table yields `EMPTY`, not `OK` — asserted explicitly, because folding the two is the risk that would let an unloaded warehouse pass goal-01.
- An `ApiException` with a canned 400 body yields `BROKEN` with `error` **byte-identical to the body** and the right `http_status` and `category`.
- Retry: a fake failing twice with a 503 then succeeding yields `OK` with `attempts=3`; a fake failing three times with a 400 yields `BROKEN` with `attempts=1` (non-retryable).
- Timeout: a fake that sleeps past `timeout_s=1` yields `TIMEOUT` within ~1s wall clock and the run continues — the hung-execution risk, asserted rather than hoped.
- `KeyError('properties')` yields `SKIPPED`, and `SKIPPED` is counted separately so "every visualization" is not quietly narrowed.
- **Concurrency bound:** a fake that records max simultaneous in-flight calls, run over 50 visualizations with `max_workers=4`, must never observe 5 — the "do not hammer the host" criterion asserted structurally.
- Throttle: a fake returning 429 halves the budget, emits one `ThrottleEvent` with `from_workers`/`to_workers`, and the run completes.

**Unit — `tests/test_expect.py`**
- `expected_parent_counts` on `mini_globalmart` equals `count_objects` on the same tree (the two paths cannot drift).
- `compare_counts` on equal counts is empty; on a model missing 3 metrics yields exactly one `CountMismatch` naming `metrics`, the expected and the actual.
- **Child counts are not parent counts:** `mini-sales.json` has fewer datasets than `mini_globalmart`, and comparing it against the *parent's* expectation produces mismatches — a guard test that the wiring passes each workspace its own expectation.
- `check_coverage` on the 2-domain fixture passes; with one dashboard removed from both children it fails naming that dashboard id and no other.
- `check_pruning` passes on `mini-sales.json` and, on `mini-sales-unpruned.json`, returns exactly one `PruningViolation` naming the unreachable dataset — the regression this feature owns at artifact level.
- A child whose dataset count equals the parent's yields `dataset_count_not_reduced`.

**Integration (offline) — `tests/test_verify.py`**
- All-green: a `FakeSdk` serving 13 workspaces and passing executions yields `passed=True`, `failure_reasons == []`, `len(run.workspaces) == 13`.
- **Workspace set comes from the repo:** a `FakeSdk` whose org is missing `globalmart-inventory` still produces 13 reports, with that one `present=False`, and the run fails naming it. A `FakeSdk` with an *extra* workspace does not grow the report.
- One broken visualization flips `passed` to `False`, contributes exactly one `failure_reason`, and leaves the other twelve workspaces green.
- `--fail-on-empty` off: a workspace of all-empty results is `passed=True` but carries the >50% `empty_ratio` warning; on: the same run fails.
- `systemic_category` is set when every failure in a workspace shares a category, and `None` when they differ.
- A WDF-warning fake produces the warning **before** any execution is recorded — asserted by call ordering on the fake.

**Unit — `tests/test_equivalence.py`**
- Two `FakeSdk`s serving the same tree resolved for two different profiles: `compare_orgs` returns `equivalent=True` and `differing_paths == []` after masking, while the raw digests differ — proving the masking is doing the work and the test is not vacuous.
- One metric title changed in org B yields `equivalent=False` with exactly one differing path naming that metric.

**Integration (offline) — `tests/test_rebuild.py`**
- Step order is pinned: a full `cold_rebuild` against `FakeSdk` with `apply=True` records 17 steps in the documented order, each `OK`.
- **`--apply` threading (ADR 002):** `cold_rebuild(..., apply=False)` records **zero** write calls on the fake — no datasource upsert, no workspace upsert, no PUT, no warehouse load — while still producing a full step plan with `status=PLANNED` and a non-empty `cli_equivalent` per step. A separate test asserts the *default value* of `apply` is `False`.
- Empty-org probe: a fake whose org already holds `globalmart` raises `RebuildAbortedError` unless `allow_existing=True`, and `started_from_empty_org` is `False` in that case — the honesty guard on the goal-01 claim.
- A failing publish short-circuits: subsequent steps are `SKIPPED`, the report carries the exception text, and `passed=False`.

**Unit — `tests/test_report.py`**
- `render_json` round-trips: `load_run(write_reports(run)[0]) == run`.
- `render_markdown` on `run_fail.json` lists broken visualizations before OK ones, names every broken object id, and contains each broken viz's verbatim error.
- The fixed "what this report cannot tell you" paragraph is present in every rendered report — the honesty statement is a test, not a convention.
- `verification_report.md` is regenerable from `verification_result.json` alone, with no host and no SDK import.
- `schema_version` is `1` and is the first key in the JSON.

**Unit — `tests/test_cli.py`** (extended, not replaced)
- `verify` has no `--apply` and no `--dry-run` flag (asserted by parsing, so the STEERING CLI convention cannot rot), and `--list-only` records zero `for_visualization` calls.
- Exit codes: 0 on pass, 1 on a verification failure, 2 on a missing profile key — with zero SDK calls in the last case.
- `rebuild --apply` is the only path that reaches a write, and `rebuild` without it exits 0 having written nothing.

**Static — `tests/test_no_hardcoded_identifiers.py`** (extended)
- The FEAT-002 walk now covers the new modules; the 13-workspace set must come from `domains.yaml`, so no `globalmart-<domain>` literal may appear in `src/globalmart/verify.py` or `rebuild.py`.

**Manual, once, user-initiated (per STEERING § AI Behavior)**
- `globalmart verify --target demo-cloud --list-only`, then the full `verify`, then `verify equivalence --target-a demo-cloud --target-b local-inference`, then the whole `rebuild --target fresh-org --apply` into a genuinely empty org — the last of which is the goal-01 measurable outcome, executed once and its `verification_result.json` kept.

---

### Total Effort Estimate

| Scale | Meaning |
|---|---|
| S | A few hours |
| M | 1–3 days |
| L | 1–2 weeks |
| XL | More than a sprint — consider splitting the feature |

**Overall: M–L (4–6 days).** The execution loop is genuinely the predecessor's, already proven over 13 workspaces, so `classify.py` and the core of `execute.py` are a port plus the `EMPTY`/`SKIPPED`/throttle additions — a day. The real work is (a) `expect.py`'s reachability closure for the pruning check, which is the same shape of graph walk FEAT-004 does and must be written independently of it to be worth anything, (b) extending `FakeSdk` far enough that timeouts, retries, throttling and a 13-workspace org are all testable without a host, which is what makes the tester testable, and (c) `rebuild.py`'s step orchestration, which is mostly glue but has to thread `--apply` through five other features' functions without loosening any of their gates. Fits the `m` appetite on the assumption that FEAT-001–005 have landed; if `rebuild` has to be written against unfinished FEAT-004/005 signatures, that step slips and the rest still stands.

---

### Implementation Order

Deliberately ordered so the four verification axes land in decreasing independence — `classify` needs nothing, `rebuild` needs everything.

1. **`classify.py` + `tests/fixtures/verification/errors/` + `tests/test_classify.py`** — the port. Pure, no dependencies, and it is what turns an error string into an actionable line in the report. Everything downstream consumes `Failure`.
2. **`FakeSdk` extension in `tests/conftest.py`** — `get_visualizations`, programmable `for_visualization` (table / empty table / raise / sleep), `list_workspaces`. Written before `execute.py` so the executor is built against its own test double rather than retrofitted.
3. **`execute.py` + `tests/test_execute.py`** — `VizResult`, `ExecStatus`, the inner-daemon-thread timeout, the retry policy, `Throttle`, the shared pool. The concurrency-bound and timeout tests land here, because they are the two behaviours that cannot be checked by reading the code.
4. **`preflight.py` — `check_wdf_values`** — small, self-contained, and it must exist before the first multi-workspace run or a systemic 400 will be misread as content breakage.
5. **`expect.py` + `tests/fixtures/mini_domains/` + `tests/test_expect.py`** — counts, coverage, pruning. The fixture set (including the deliberately unpruned negative case) is the deliverable here as much as the code.
6. **`report.py` + `tests/fixtures/verification/run_*.json` + `tests/test_report.py`** — built before `verify.py` so the orchestrator has a finished output contract to fill, and so the Markdown renderer is proven against committed runs rather than against whatever the first live run happened to produce.
7. **`verify.py` + `tests/test_verify.py`** — assembles 3–6 into `VerificationRun`, resolves the 13-workspace set from `domains.yaml`, computes `passed` and `failure_reasons`.
8. **`compare.dict_diff` + `equivalence.py` + `tests/test_equivalence.py`** — the cross-org axis, reusing FEAT-002's `mask_parameters` untouched.
9. **`cli.py` — `verify` and `verify equivalence`** — flags, the `--list-only` path, exit codes, the profile `verify:` block, `.gitignore` entry. Extend `tests/test_cli.py`.
10. **`rebuild.py` + `tests/test_rebuild.py`** — last, because it calls four other features' functions; the step-order, `--apply`-threading and empty-org-probe tests are the ones that make "no manual step" a checked claim.
11. **`cli.py` — `rebuild`** — plus the step-plan printer for the no-`--apply` rehearsal.
12. **`docs/verification.md`** — the four axes, the stated limits, the JSON schema, the exit-code contract, the fresh-org runbook.
13. **The live runs (user-initiated)** — `--list-only`, then `verify` against demo cloud, then `verify equivalence` across two orgs, then the full cold `rebuild --apply` into an empty org, whose `verification_result.json` is the evidence for goal-01.
