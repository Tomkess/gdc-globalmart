---

## Technical Breakdown — FEAT-018: Cold rebuild publishes the knowledge corpus after the domain workspaces exist

This is an `xs` feature: one block moved in `_plan`, two comment/docstring corrections, and a
handful of test changes. The breakdown is short because the design is short. No interface in
`CONTRACT.md` changes: step names, `RebuildOptions`, `RebuildReport`, the `globalmart rebuild`
flags and `knowledge_docs.py`'s public functions all stay as they are. So `CONTRACT.md` is not
amended in this feature's commit.

### Components

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|
| `rebuild._plan` (`src/globalmart/rebuild.py`) | Builds the ordered `list[RebuildStep]`. The `corpus_step` block (`RebuildStep(name="publish-knowledge-docs", ...)` plus its two `SKIPPED` branches for `opts.skip_knowledge_docs` and a missing `opts.corpus_path`) moves out from between `publish-parent` and `split` to **after** `publish-domains` and **before** the optional `verify`. Its SKIPPED logic does not change. | existing, modified | S |
| `_plan`'s corpus-step comment | The current comment explains *why* the step exists (the corpus is not in the layout tree) and where it writes (`knowledge_scope`, ADR 010). It does not explain *where the step sits*, and that gap is how the bug stayed hidden. Add one sentence: under `knowledge_scope: workspaces` the step writes into every workspace in `corpus_workspaces(manifest)`, and `publish_corpus`'s first call (`list_documents()`) does not tolerate a 404, so the step has to run after `publish-domains` has created those workspaces. The ordering is deliberate; do not move the step earlier. | existing, modified | S |
| `rebuild.py` module docstring | The chain diagram (`probe the org -> verify the committed data -> ... -> publish each child -> verify the result`) does not mention the corpus step at all. Insert `-> publish the knowledge corpus` between `publish each child` and `verify the result`. | existing, modified | S |
| `step_runner`'s `runners` dict | Only used for lookup, so its order has no effect on behaviour. Reorder the `"publish-knowledge-docs"` entry to sit after `"publish-domains"` so the dict reads in chain order. This is readability only; no change to the `no runner for planned step` guard. | existing, modified (cosmetic) | S |
| `_run_publish_knowledge_docs` | **Unchanged.** Still calls `publish_for_target(profile, documents, workspaces=corpus_workspaces(manifest), apply=True)`, raises `GlobalmartError` on `report.failed` / `report.cleanup_incomplete`, and returns the `scope=...` detail. The docstring's "a failed upsert stops the chain" is still accurate. | existing, untouched | — |
| `_run_split`, `_run_publish_domains` | **Unchanged.** The reorder depends on one existing guarantee here: `publish.publish_domains` raises `GlobalmartError` whenever any domain fails. With the default `keep_going=False` (which `_run_publish_domains` uses) it raises at the first failure. Even with `keep_going=True` it raises after the loop if `failures` is non-empty. So `publish-domains` reports `OK` only when all twelve children published. | existing, relied on | — |
| `tests/test_rebuild.py` | Updates the exact-sequence assertions to the new order and replaces the stale FEAT-015 adjacency test. Adds tests for the three guarantees in the ACs: every workspace the corpus writes to already exists, a failed `publish-domains` never reaches the corpus step, and `organization` scope is unchanged (see Test Strategy). | existing, modified | S |

**Not touched, per the spec's Out of Scope:** `knowledge_docs.py`. `publish_corpus` keeps its
404-intolerant `list_documents()`. `remove_ours` keeps its 403/404 `absent=True` handling.
`publish_for_target` and `corpus_workspaces` are unchanged. No new flag and no new
`RebuildOptions` field.

**How AC5 ("publish-domains skipped or fails → corpus does not silently upsert") is met without
new logic:**

- **Fails:** `cold_rebuild`'s execution loop already records a raising step as
  `StepStatus.FAILED`, sets `report.passed = False` and raises `RebuildAbortedError(f"step
  {step.name!r} failed: ...")`. Nothing after it runs. Now that `publish-knowledge-docs` comes
  after `publish-domains`, a domain publish failure stops the chain before the corpus step
  starts. The error names the failed domain (`publishing domain 'x' failed: ... not attempted:
  ...`), which is the loud, named failure the AC asks for, and never a 404 raised from the
  corpus step.
- **Skipped:** today `_plan` never marks `publish-domains` as `SKIPPED`: no flag or option
  skips it, and `--skip-data` drops only `verify-data` and `load-warehouse`. So this branch
  cannot happen in the current code. The exact-sequence tests are what keep it that way: if a
  future change makes `publish-domains` skippable, the diff has to touch those assertions, and
  that is where the corpus dependency will be seen. See the [DECISION NEEDED] below for whether
  to also add a runtime guard.

> **[DECISION NEEDED] — runtime guard for a skipped `publish-domains`.** Option (a),
> recommended: no runtime code. The branch cannot happen today, and the exact-sequence tests
> plus the new `_plan` comment lock the dependency in. Option (b): in `cold_rebuild`'s
> execution loop, if `publish-domains` is `SKIPPED` (or absent from the plan) and the profile's
> `knowledge_scope` is `WORKSPACES`, mark `publish-knowledge-docs` as `FAILED` with detail
> `"publish-domains did not run; domain workspaces may not exist"` before it is attempted.
> Option (b) adds about 8 lines and one test, and guards against a state nothing can produce
> yet. It also goes beyond the spec's "a reorder, not new logic". Pick (a) unless the owner
> expects a `--skip-domains` style flag soon.

### Data Model

No new tables, schemas, dataclasses or fields. `RebuildStep`, `RebuildReport`, `RebuildOptions`
and `StepStatus` keep their current shapes. The only data that changes is the **order of the
`RebuildReport.steps` list** for a default plan:

```
before: probe-org, verify-data, load-warehouse, publish-parent, publish-knowledge-docs, split, publish-domains, verify
after : probe-org, verify-data, load-warehouse, publish-parent, split, publish-domains, publish-knowledge-docs, verify
```

With `skip_data=True`, the same list without `verify-data` and `load-warehouse`. With
`verify=False`, the same list without `verify`. The position of `publish-knowledge-docs` in the
report is the same whether it is planned or `SKIPPED`, so a named skip still appears in the
report at its new position.

### Integration Points

- **`globalmart.knowledge_docs.publish_for_target` / `corpus_workspaces`** (FEAT-015 + FEAT-017,
  interfaces per `CONTRACT.md`). The consumer whose precondition this feature restores. Under
  `KnowledgeScope.WORKSPACES` it calls `publish_corpus` once per id in
  `corpus_workspaces(manifest)` (parent plus twelve children, which is the "13 workspaces" the
  existing detail test asserts), and each call starts with `list_documents()`, which raises
  `KnowledgeDocsError` on a 404. After the reorder, all thirteen exist when this runs: the
  parent from `publish-parent`, the children from `publish-domains`.
  Under `KnowledgeScope.ORGANIZATION` there is one write to the organization level, which
  always exists, and a cleanup pass (`remove_ours`) over the thirteen workspaces. That pass
  already treats a missing workspace as `absent=True`. After the reorder the pass finds real,
  empty workspaces instead of 404s. The outcome is the same (nothing of ours removed, cleanup
  complete), so AC4's "behaviour unchanged" holds.
- **`globalmart.publish.publish_domains`** (FEAT-004). As described above, it raises on any
  domain failure, and that is what AC5 relies on. No change.
- **`globalmart.split.split_all`** (FEAT-004). Offline and writes local files only. Nothing in it
  reads knowledge state, so moving the corpus step after it has no effect on it.
- **`globalmart.verification.verify_target`** (FEAT-006). Runs AFM executions over
  visualizations and does not read AI Knowledge. It ran after the corpus step before this
  change and still does, so its position relative to the corpus step does not change.
- **CLI (`globalmart rebuild`)**: no flag change. `--skip-knowledge-docs` and `--corpus` keep
  their meaning. Only the order of the printed step lines in the rehearsal report changes.
- **Other references to the step order**: a repo search for `publish-knowledge-docs` outside
  `rebuild.py` and `tests/test_rebuild.py` finds nothing in `src/`, `tests/`, `docs/` or
  `README.md`. No other code or documentation encodes the old position.
- **Goal-01**: this removes the known blocker to a cold rebuild into a fresh org under the
  default scope. A live fresh-org run remains the eventual proof and is out of scope here.

### Test Strategy

All tests are unit tests in `tests/test_rebuild.py`, following the file's existing patterns:
`ProbeSdk([])` for an empty org, `with_corpus(tmp_path)` so the corpus step is planned rather
than skipped, and `monkeypatch.setattr(rebuild_module, "step_runner", runner_for)` to record the
execution order. No live host (STEERING: AI Behavior).

**Updated:**

1. `test_a_rehearsal_plans_every_step_and_runs_none`: exact-list assertion changed to
   `["probe-org", "verify-data", "load-warehouse", "publish-parent", "split",
   "publish-domains", "publish-knowledge-docs", "verify"]`. It stays a full `==` comparison,
   never a subset or `index` check (AC3). The `[StepStatus.PLANNED] * 7` assertion is
   unchanged.
2. `test_a_successful_chain_runs_every_step_in_order`: `calls` exact list changed to the same
   order minus `probe-org`.
3. `test_the_corpus_is_published_right_after_the_parent` → **replaced** by
   `test_the_corpus_is_published_only_after_the_domain_workspaces_exist`. Its FEAT-015
   docstring ("children inherit at read time, so it does not wait on `split`") is the stale
   reasoning this feature removes. The new test asserts `names.index("split") <
   names.index("publish-domains") < names.index("publish-knowledge-docs")` and that
   `publish-knowledge-docs` is immediately followed by `verify` (AC2). Its docstring states the
   actual reason: `publish_corpus` does not tolerate a 404, and under `workspaces` scope it
   writes into every child.
4. `test_a_failed_corpus_publish_stops_the_chain`: additionally record `calls` and assert
   `"verify" not in calls`. This locks in that the corpus step now sits before `verify` and
   still stops the chain.

**Added:**

5. `test_skip_data_keeps_the_corpus_after_the_domains`: exact list for
   `with_corpus(tmp_path, skip_data=True)`: `["probe-org", "publish-parent", "split",
   "publish-domains", "publish-knowledge-docs", "verify"]`. This covers the spec's "re-run
   rehearsal tests for `--skip-data` interactions".
6. `test_a_skipped_corpus_step_keeps_its_place_in_the_report`: with `skip_knowledge_docs=True`,
   the `SKIPPED` step is still at the position right after `publish-domains`, so the named gap
   appears where the step would have run.
7. `test_every_corpus_workspace_exists_before_the_corpus_step_runs` (AC1). Fake runners share
   one `created: set[str]`. The `publish-parent` runner adds `manifest.parent_workspace_id`.
   The `publish-domains` runner adds every `manifest.by_key(k).workspace_id`. The
   `publish-knowledge-docs` runner asserts `set(corpus_workspaces(manifest)) <= created`,
   raising `RuntimeError("404: ...")` on a miss so the test fails as the real bug would.
   Running `cold_rebuild(..., apply=True, options=with_corpus(tmp_path))` must return
   `report.passed`. Against the old order this test fails, which shows it actually covers the
   bug.
8. `test_a_failed_domain_publish_never_reaches_the_corpus_step` (AC5). The `publish-domains`
   fake raises `GlobalmartError("publishing domain 'sales' failed: ...")`. Assert
   `pytest.raises(RebuildAbortedError, match="publish-domains")`, and that `calls` ends with
   `"publish-domains"` and does not contain `"publish-knowledge-docs"` or `"verify"`.
9. `test_the_plan_does_not_depend_on_knowledge_scope` (AC4). Build the rehearsal twice, with
   `replace(profile(), knowledge_scope=KnowledgeScope.WORKSPACES)` and with `ORGANIZATION`, and
   assert the two `[s.name for s in report.steps]` lists are equal. The existing parametrized
   `test_the_corpus_step_detail_names_the_scope` and `test_a_failed_corpus_cleanup_fails_the_chain`
   stay as they are and still cover the organization-scope runner behaviour. They call
   `_run_publish_knowledge_docs` directly, so the reorder does not affect them.

**Unchanged, re-run to confirm nothing else assumed the old order:**
`test_every_step_carries_the_command_that_reproduces_it`, `test_every_planned_step_has_a_runner`,
`test_a_failing_step_stops_the_chain` (fails at `load-warehouse`, before either moved step),
`test_an_absent_corpus_is_a_named_skip_not_an_omission`,
`test_skip_knowledge_docs_says_so_in_the_report`,
`test_a_skipped_corpus_step_does_not_run_and_does_not_fail_the_chain`, plus the full
`uv run pytest` suite and the CI gate's rehearsal tests.

**Manual:** `globalmart rebuild --target <profile>` (rehearsal, no `--apply`) prints the plan in
the new order. A live fresh-org `--apply` run is out of scope per the spec.

### Total Effort Estimate

| Scale | Meaning |
|---|---|
| S | A few hours |
| M | 1–3 days |
| L | 1–2 weeks |
| XL | More than a sprint — consider splitting the feature |

**Overall:** S (about 2–3 hours: roughly 20 changed lines in `rebuild.py` and about 6 test
changes or additions). This fits within the spec's `xs` appetite. The document is short on
purpose, because the design really is a reorder.

### Implementation Order

1. **Write the new failing tests first.** Tests 7 (`test_every_corpus_workspace_exists_before_the_corpus_step_runs`)
   and 8 (`test_a_failed_domain_publish_never_reaches_the_corpus_step`), and update the exact
   lists in tests 1 and 2. Confirm 1, 2 and 7 fail against the current order. Test 8 fails too:
   the corpus step currently runs before `publish-domains`, so it does appear in `calls`.
2. **Reorder `_plan`**: move the `corpus_step` block after the `publish-domains` append and before
   the `if opts.verify:` block, and extend its comment with the ordering rationale.
3. **Cosmetic follow-ups in `rebuild.py`**: reorder the `runners` dict entry and update the
   module docstring's chain diagram.
4. **Replace and extend the remaining tests**: 3 (replace the stale adjacency test), 4, 5, 6, 9.
5. **Run the full suite** (`uv run pytest`) and a `globalmart rebuild` rehearsal to confirm the
   printed order. Apply the [DECISION NEEDED] outcome: nothing for option (a), or one guard plus
   one test for option (b).

---
