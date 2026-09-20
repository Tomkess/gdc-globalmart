---
abandoned_at: null
abandoned_reason: null
appetite: m
blocked_at: null
blocked_by: null
confidence: high
created: '2026-09-18'
cycle: null
depends_on:
- feat-001
- feat-002
- feat-003
- feat-004
- feat-005
enables: []
goal: goal-01
id: feat-006
name: 'Rebuild verification: cold-rebuild smoke test that executes every visualization
  in the parent and every domain workspace and reports failures'
sources: []
status: done
tags: []
updated: '2026-09-20'
---

## Summary

goal-01 claims that "a clean clone of this repo plus credentials for an empty GoodData org rebuilds
the parent workspace and all 12 domain workspaces, with every visualization executing successfully
and no manual step." FEAT-006 is the harness that decides whether that sentence is true on any given
day. It drives the whole chain end to end — generate and load the row data (FEAT-005), publish the
parent (FEAT-002), generate and publish the 12 children (FEAT-004) — and then verifies the result
along four axes: every one of the 384 parent visualizations and every child visualization actually
computes against the warehouse; the object counts match what the repo says they should be; the 12
domains between them cover every parent dashboard and visualization; and the same repo state
published into two different orgs yields normalized layouts identical except for the parameterized
values. It emits a machine-readable `verification_result.json` that can gate CI and a
broken-first `verification_report.md` that names every failure with its object id, its HTTP status
and the server's error verbatim. The predecessor smoke tester (`Misc/scripts/smoke_test.py` plus its
`classifier.py`) already proved the execution half of this against 13 workspaces; its structure —
WDF preflight, thread pool with a hard per-viz timeout, failure taxonomy with remediation hints,
JSON + Markdown output, non-zero exit on any breakage — is adopted rather than reinvented, and
extended with the rebuild, coverage, count and equivalence axes that make it a proof of goal-01
rather than a health check on a live org.

## Appetite

`m` — 1–2 weeks

## Acceptance Criteria

- [x] Given a published target profile, when `globalmart verify --target <profile>` runs, then every
      visualization in the parent workspace and in all 12 domain workspaces is executed against the
      warehouse, and the command exits 0 only if zero visualizations are broken.
- [x] Given a visualization that fails to execute, when the run completes, then the report names its
      workspace id, object id, title, the HTTP status, the server's error body verbatim, a taxonomy
      category and a remediation hint — never an aggregate count alone.
- [x] Given a visualization that executes successfully but returns zero rows, when the run completes,
      then it is reported with status `EMPTY` and counted separately from `OK` — a technically valid
      empty result is surfaced, not hidden, and `--fail-on-empty` can promote it to a failure.
- [x] Given a completed run, when the output directory is inspected, then it contains
      `verification_result.json` (a versioned, machine-readable `VerificationRun`) and
      `verification_report.md` (broken-first, human-readable), both regenerable from the JSON alone.
- [x] Given the repo's committed artifacts, when verification runs, then each workspace's live object
      counts are compared against counts derived from the repo — the parent against
      `layouts/workspaces/globalmart/` (225 datasets, 1075 metrics, 384 visualization objects, 32
      dashboards, 2 date instances) and each child against its own
      `generated/workspaces/globalmart-<domain>.json` — and any mismatch fails the run naming the
      object type and both numbers. Child counts are never compared against the parent's.
- [x] Given the parent and the 12 generated children, when coverage is checked, then every parent
      dashboard id and every parent visualization id appears in at least one child, and any id
      appearing in none fails the run by name.
- [x] Given each generated child, when the pruning invariant is checked, then the child's LDM
      contains no dataset unreachable from that child's retained metrics and visualizations, and its
      dataset count is strictly less than the parent's 225.
- [ ] **NOT MET (the rehearsal half is; the cold half is not).** Given credentials for an empty org
      and a clean clone, when `globalmart rebuild --target <profile> --apply` runs, then data
      generation, warehouse load, parent publish, child generation and child publish execute in order
      with no manual step between them, and verification runs at the end; without `--apply` the same
      command is a rehearsal that writes nothing and prints the step plan.
      *(The rehearsal, the step plan and the empty-org probe all work and are tested. No empty org
      was available, and the probe correctly refuses to report a warm org as a cold rebuild, so the
      end-to-end chain has never executed. Needs a throwaway org.)*
- [x] Given two target profiles, when `globalmart verify equivalence --target-a <a> --target-b <b>`
      runs, then both orgs' layouts are fetched, passed through `compare.mask_parameters()` and
      compared, and the command fails listing every differing field path if anything outside host,
      org, datasource id and schema differs.
- [x] Given a workspace whose visualizations all fail, when the run starts, then the WDF preflight
      has already reported whether the workspace has a data filter defined with no value set — so a
      workspace-wide 400 is diagnosed as one configuration fault, not 384 visualization defects.
- [x] Given a run against a host, when execution is parallelized, then the number of concurrent
      executions in flight across the whole run never exceeds `--max-workers` (default 8), each
      execution is bounded by `--viz-timeout` (default 180s), and a `TRANSIENT_5XX` or 429 is retried
      up to `--max-retries` (default 2) with backoff before being recorded as broken.
- [x] Given no credentials and no host, when `uv run pytest tests/ -x -q` runs, then the whole
      harness — execution loop, classifier, counts, coverage, pruning, reporting, rebuild step
      sequencing and equivalence masking — is exercised against `FakeSdk` and committed fixtures, and
      the only thing not covered offline is the live warehouse and the live server's validation.

## Scope

- `globalmart verify --target <profile>` — the core command: WDF preflight, list visualizations,
  execute every one, classify failures, assert counts, check coverage and pruning, write both
  reports, exit non-zero on any failure.
- A failure taxonomy (`classify.py`) ported from the predecessor's `classifier.py`, extended with
  `EMPTY_RESULT` and `RATE_LIMITED`, as a pure function over `(error_text, http_status)`.
- Repo-derived expectations: `ObjectCounts` (FEAT-001's) computed from the committed parent tree and
  from each committed child JSON, so the assertion source is the repo, never a live org.
- Coverage and pruning assertions over the generated children as *artifacts*, independent of the
  FEAT-004 code that produced them.
- `globalmart rebuild --target <profile> [--apply]` — a step orchestrator that chains FEAT-005's data
  generation and load, FEAT-002's parent publish, FEAT-004's child generation and publish, and
  finally `verify`, with per-step status and timing, honouring ADR 002 (`--apply` gates every remote
  write, in every step).
- `globalmart verify equivalence --target-a <a> --target-b <b>` — cross-org equivalence built on
  `compare.mask_parameters()`.
- Two output formats: `verification_result.json` (schema-versioned, the CI gate and the historical
  record) and `verification_report.md` (broken-first human summary), with the Markdown renderable
  from a stored JSON so old runs can be re-rendered.
- An offline test suite covering every module against `FakeSdk` and committed fixtures.

## Out of Scope

- **Semantic correctness of results.** The harness proves a visualization computes; it does not know
  what number it should return. Value-level assertions are a separate feature and would need a
  golden-results fixture that FEAT-005's deterministic generator makes possible but does not supply.
- **Dashboard rendering.** Executions go through visualization objects and AFM; dashboard layout,
  drills, and filter-context wiring are not exercised. A dashboard can be verified-green and still
  render broken.
- **AI-context verification.** That `memoryItems`, agent personalities and AI knowledge survived the
  publish is asserted structurally (counts and presence), never behaviourally — no LLM is called and
  no answer quality is measured. An AI-context regression that leaves the objects present but wrong
  passes this harness.
- **Provisioning the empty org**, its users, groups, permissions or LLM providers — FEAT-002 already
  declares this out of scope and `rebuild` assumes the org exists and the token reaches it.
- **Re-testing FEAT-004's pruner algorithm.** FEAT-006 asserts the invariant on the committed
  artifacts; the unit tests that prove the closure algorithm correct belong to FEAT-004. See the
  decision in Open Questions.
- **Performance benchmarking.** Durations are recorded per visualization because they are free, but
  no threshold is asserted and no regression is flagged on timing.
- **Automatic repair.** The harness names what broke; fixing it is a change to the parent tree,
  `domains.yaml` or the splitter.

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **A visualization executes successfully and returns semantically wrong numbers** — the harness cannot tell | High | High | Stated as a known limit in the report header and here. Partially mitigated by recording `row_count` per visualization in the JSON, so a run-over-run collapse (e.g. 50k rows → 3) is visible to whoever compares two runs; FEAT-005's deterministic generator makes a golden-results feature possible later, and this feature deliberately does not claim it |
| **An empty result is technically valid and indistinguishable from a broken pipeline** — an unloaded warehouse can look green | High | High | `EMPTY` is its own status, counted and listed separately from `OK`, never folded into the pass count; `--fail-on-empty` promotes it to a failure; a run in which >50% of a workspace's visualizations are `EMPTY` emits a workspace-level warning naming the likely cause (warehouse not loaded / wrong schema) |
| **An AI-context regression is invisible** — every visualization computes while AI memory, knowledge or personalities were silently dropped on publish | Medium | High | Out of scope for execution testing, so it is asserted structurally instead: the count assertion includes AI-context object counts from the repo tree, and a zero-where-repo-says-N fails the run. Behavioural AI quality is explicitly not claimed |
| **A workspace-wide misconfiguration is reported as N visualization defects**, burying the one real cause | High | Medium | WDF preflight runs before execution (the predecessor's #1 finding); the report surfaces the workspace-level warning above the per-object list, and a workspace where 100% of executions share one taxonomy category is summarized as a single systemic finding |
| **Flaky infrastructure is recorded as a deterministic defect**, or a real defect is retried into a pass | Medium | Medium | `TRANSIENT_5XX`/`RATE_LIMITED` are the only retried categories, bounded at `--max-retries`; `attempts` is recorded per visualization so a "passed on attempt 3" is visible in the JSON and never silently green |
| **Count assertions are tautological** — the repo generates the artifact and the repo is also the expectation | Medium | Medium | Expectations come from the committed artifacts, but the comparison is against what the *live org* reports back after publish, which catches server-side rejection, truncation and partial application. The parent's absolute numbers (225/1075/384/32/2) are additionally pinned as literals in a test so a wholesale regeneration that halves the parent fails loudly |
| **The parallel run overloads the host**, and the resulting 5xx storm is read as content breakage | Medium | High | One bounded executor for the whole run, not one per workspace; `--max-workers` default 8, workspaces sequential by default; on a 429 or a burst of 5xx the effective concurrency halves for the remainder of that workspace, and the throttle event is recorded in the report |
| **A hung execution blocks the run indefinitely** (`ThreadPoolExecutor` cannot cancel in flight) | Medium | Medium | The predecessor's pattern is kept: each execution runs in an inner daemon thread joined with a hard `--viz-timeout`; a timeout is recorded as `TIMEOUT` and the run continues |
| **`for_visualization()` raises on non-insight visualization types** (`local:table`), producing a bare `KeyError('properties')` that reads as a defect | Medium | Low | `UNSUPPORTED_TYPE` taxonomy entry retained from the predecessor; such objects are recorded `SKIPPED` with the reason, and the skipped count appears in the summary so the "every visualization" claim is not quietly narrowed |
| **The cold rebuild is only ever run against an already-populated org**, so "empty org" is never actually tested | Medium | High | `rebuild` records `started_from_empty_org` by probing the org's workspace list before step 1 and refuses to claim a cold rebuild when the target already holds `globalmart`, unless `--allow-existing` is passed; the flag's absence is what makes the goal-01 claim honest |
| **The harness passes because it silently verified fewer workspaces than it should** | Medium | High | The set of workspaces to verify is derived from `domains.yaml` plus the parent, not from what the org happens to contain; a workspace the repo expects and the org lacks is a failure, and the run asserts exactly 13 workspace reports |
| **Live runs are expensive and slow enough that nobody runs them**, so the goal-01 claim rots | Medium | Medium | The whole harness is provable offline against `FakeSdk`, so regressions in the *harness* are caught on every PR; the live run is a single command with a single credential set, and its JSON output is designed to be tracked over time |

## Dependencies

- **Depends on:** feat-001 (`read_tree`, `count_objects`/`ObjectCounts`, the committed parent tree),
  feat-002 (`publish_workspace`, `PublishResult`, `compare.mask_parameters`, `make_sdk`,
  `TargetProfile`/`load_profile`, `FakeSdk` in `tests/conftest.py`), feat-003 (`domains.yaml` — the
  authoritative list of the 12 domains and their child workspace ids), feat-004 (the generated child
  JSON artifacts and their publish path), feat-005 (row data in the warehouse — without it every
  execution returns empty or fails).
- **Enables:** the goal-01 measurable outcome. Nothing else in the current feature set depends on it.
- **External:** `gooddata-python-sdk` (`sdk.visualizations.get_visualizations`,
  `sdk.tables.for_visualization`, `sdk.catalog_workspace.get_declarative_workspace`,
  `sdk.catalog_workspace.list_workspaces`), raw REST for the two `workspaceDataFilter*` endpoints the
  SDK does not cover, credentials for at least one target org, and a loaded warehouse.

## Related Research

- `Misc/scripts/smoke_test.py` — the working predecessor. Executes every visualization in each of 13
  workspaces via `sdk.tables.for_visualization(workspace_id, viz, always_two_dimensional=True)`,
  which is the only reliable breakage detector because **no JSON property marks a visualization as
  broken**. Its structure is adopted: `Config` from a YAML naming env vars rather than holding
  secrets; a WDF preflight per workspace; `ThreadPoolExecutor` with an inner daemon thread per
  execution to enforce a hard timeout the pool cannot; `VisualizationResult` / `WorkspaceReport` /
  `SmokeTestRun` dataclasses serialized with `asdict`; JSON plus a broken-first Markdown report;
  exit code 1 when anything is broken. What changes here: config comes from `TargetProfile`, not a
  separate `workspaces.yaml`; the workspace list comes from `domains.yaml`; and execution is one of
  four verification axes rather than the whole feature.
- `Misc/scripts/classifier.py` — an 11-entry failure taxonomy (`WDF_NO_VALUE`, `PROTECTED`,
  `INVALID_IDENTIFIER`, `LDM_MAPPING`, `DATA_LIMIT`, `CALC_ERROR`, `TOO_LARGE_TIMEOUT`,
  `TRANSIENT_5XX`, `UNSUPPORTED_TYPE`, `TIMEOUT`, `UNKNOWN`) with a remediation hint per category,
  matched in priority order by substring over the lowercased error plus an HTTP status extracted by
  regex from the exception string. Pure, so fully unit-testable with canned strings. Ported as-is and
  extended with `EMPTY_RESULT` and `RATE_LIMITED`.
- The predecessor's single most valuable finding: a workspace that inherits a WDF *definition* with
  no filter *value* set fails **every** execution with HTTP 400 ("filter values ... are empty"),
  which in the UI reads as "SORRY, WE CAN'T DISPLAY THIS VISUALIZATION" on every tile. Without the
  preflight this presents as total content breakage. FEAT-001 defaults to `WdfPolicy.DROP`, which
  should make this impossible in a repo-built org — the preflight stays precisely to prove that.
- STEERING § Architecture Constraints: "Coverage is enforced — every dashboard and visualization in
  the parent must land in at least one domain, or the split fails loudly." FEAT-004 enforces this at
  generation time; FEAT-006 re-asserts it against the committed artifacts, so a hand-edited or stale
  generated file cannot slip through.
- STEERING § Portability Contract, final line: "publishing the same repo state into two different
  orgs yields workspaces whose normalized layouts are identical except for the parameterized values."
  FEAT-002 proved this offline with two `FakeSdk`s; FEAT-006 proves it against two live orgs using
  the same `mask_parameters()` function, which exists for exactly this purpose.
- ADR 002: every remote write is gated on `--apply`. `verify` is read-only and therefore takes no
  `--apply`; `rebuild` wraps commands that write and so must thread `--apply` through every step
  rather than defining its own gate.
- FEAT-002 § Out of Scope explicitly defers two things to here: "Publishing a workspace against an
  empty warehouse must succeed; only execution of visualizations will fail, which FEAT-006 reports"
  and "Verifying that visualizations actually compute (FEAT-006)."

## Open Questions

- ~~Should FEAT-006 assert the pruning regression, or leave it to FEAT-004's own tests?~~
  **Resolved 2026-09-18: both, at different levels, and they are not redundant.** FEAT-004 owns the
  unit tests that prove the *closure and pruning algorithm* is correct against fixtures. FEAT-006
  asserts the *invariant on the committed artifacts and the live children* — for each generated
  child, no dataset in its LDM is unreachable from that child's retained metrics and visualizations,
  and its dataset count is strictly less than the parent's 225. This catches what FEAT-004's tests
  structurally cannot: a stale generated file committed before a pruner fix, a hand-edited generated
  file (which STEERING calls a defect), and a child published from an artifact that no longer matches
  the parent. It is one function (`check_pruning`) reading the artifacts, with no dependency on
  FEAT-004's internals, so the coupling cost is near zero.
- ~~Is execution best driven through `sdk.tables.for_visualization` or a hand-built AFM?~~
  **Resolved 2026-09-18: `for_visualization`.** It is the path the predecessor proved over 13
  workspaces, it resolves the visualization's own filters and attributes exactly as the UI does, and
  a hand-built AFM would test the harness's AFM construction rather than the content. The known cost
  is that non-insight types raise `KeyError('properties')`; that is handled by the
  `UNSUPPORTED_TYPE` category and a `SKIPPED` status rather than by switching execution paths.
- ~~Should `verify` fail on empty results?~~ **Resolved 2026-09-18: no by default, yes under
  `--fail-on-empty`.** A legitimately empty slice exists in GlobalMart, so a hard failure would make
  the harness cry wolf; but folding empties into `OK` would let an unloaded warehouse pass the
  goal-01 claim. `EMPTY` is therefore its own status, always visible in both reports, with a
  workspace-level warning above 50%.
- ~~Does `rebuild` re-implement the other features' commands, or shell out to them?~~
  **Resolved 2026-09-18: in-process function calls, not subprocesses.** Each step calls the owning
  feature's public function (`generate_data`, `load_warehouse`, `publish_workspace`,
  `generate_domains`), so `--apply` and exceptions propagate as values rather than exit codes, and
  the whole chain is testable against `FakeSdk`. The CLI equivalent of each step is printed in the
  step plan so a human can reproduce any single step by hand.
- **Where does the verification history live?** `verification_result.json` is written to
  `--output-dir` (default `reports/`, gitignored). Whether runs are archived per-commit, pushed to a
  bucket, or loaded into GlobalMart itself as an eval dataset is deliberately undecided — the JSON is
  schema-versioned (`schema_version: 1`) so that choice can be made later without changing the
  harness.
- **Should `verify` run as a CI job against a scratch org on merge?** Not decided here. ADR 002's
  revisit trigger anticipates exactly this (a per-profile `require_apply: false` for throwaway orgs)
  and should be revisited if the answer becomes yes; today the live run is user-initiated per
  STEERING § AI Behavior, and only the offline suite runs in CI.

## Outcome (2026-09-20)

Built and run live. 411 tests, ruff and mypy clean.

```
globalmart verify --target demo-cloud

workspaces        : 13
visualizations    : 768
  ok              : 768
  empty           : 0
  broken          : 0
  skipped         : 0
coverage          : ok          (32/32 dashboards, 384/384 visualizations)
pruning           : 0 violation(s)
passed            : True        84.0s
```

**goal-01's central claim, measured rather than asserted.** Every visualization in the
parent and in all twelve children executes against the warehouse. Not one broken, not one
empty — the empty count matters as much as the broken one, because a completely unloaded
warehouse would otherwise pass this silently.

The other two axes:

```
globalmart verify equivalence --target-a demo-cloud --target-b usecases-ai
  demo-cloud   49dabecfbeaecdd9
  usecases-ai  49dabecfbeaecdd9      equivalent: True

globalmart rebuild --target demo-cloud
  error: org 'gm-ddebmti' already holds workspaces this repo would create, so this would
  not be a cold rebuild and must not be reported as one.
```

That second output is the feature working. The empty-org probe refused to let a warm org be
reported as a cold rebuild, which is the difference between proving goal-01 and appearing to.

### What departed from the plan

1. **`verification.py`, not `verify.py`.** FEAT-004 took `verify.py` for its offline split
   gate. CONTRACT.md had flagged the collision and recommended this split; it is now done
   and recorded there.

2. **`load_run` returns a dict, not a `VerificationRun`.** The reason to load a stored run
   is to re-render its report, and reconstructing dataclasses would fail the moment the
   schema moved — which is exactly when reading an old report matters most. `render_markdown`
   therefore accepts either, and `test_the_round_trip_regenerates_the_same_markdown` pins
   that the two paths agree.

3. **Throttling never recovers.** The breakdown said the budget halves "for the remainder of
   that workspace"; it halves for the remainder of the **run**. A host that asked us to slow
   down once should not be asked again two workspaces later, and per-workspace recovery
   would re-provoke it on every workspace boundary.

4. **A single 5xx does not throttle; three consecutive ones do.** One blip is noise. The
   breakdown said "a burst" without defining it, so it is defined here and tested both ways.

### Not done

- **The cold rebuild has never run against a genuinely empty org.** Every available profile
  points at an org that already holds GlobalMart, and the probe correctly refuses to call
  that cold. The chain is proven step-by-step (each step's function is exercised in the live
  runs of FEAT-002, FEAT-004 and FEAT-005, and the sequencing is tested offline against
  `FakeSdk`), but the end-to-end "empty org to verified GlobalMart in one command" has not
  been executed. That needs a throwaway org. **This is the one acceptance criterion left
  unticked**, because the honest claim is "every link is proven and the chain is untested"
  rather than "the chain is proven".

- **No CI job runs `verify`.** It needs credentials and a live host, which STEERING keeps
  user-initiated. The offline suite covers the whole harness, so a regression in the
  *harness* is caught on every PR; a regression in a live org is not, until someone runs it.
