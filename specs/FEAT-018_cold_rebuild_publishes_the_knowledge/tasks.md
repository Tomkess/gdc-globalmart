## Tasks — FEAT-018: Cold rebuild publishes the knowledge corpus after the domain workspaces exist

> Appetite: `xs`  ·  Generated: 2026-09-29

- [x] 1. In `tests/test_rebuild.py`, update `test_a_rehearsal_plans_every_step_and_runs_none`'s
       exact step-list assertion to `["probe-org", "verify-data", "load-warehouse",
       "publish-parent", "split", "publish-domains", "publish-knowledge-docs", "verify"]`.
       Keep it a full `==` comparison, not a subset or `index` check. Confirm it fails against
       the current (unfixed) order.
       Pre: none
       AC: #2, #3
- [x] 2. In `tests/test_rebuild.py`, update `test_a_successful_chain_runs_every_step_in_order`'s
       expected `calls` list to the same order minus `probe-org`. Confirm it fails against the
       current order.
       Pre: none
       AC: #2
- [x] 3. Add `test_every_corpus_workspace_exists_before_the_corpus_step_runs` to
       `tests/test_rebuild.py`: fake runners share one `created: set[str]`; the `publish-parent`
       runner adds `manifest.parent_workspace_id`, the `publish-domains` runner adds every
       `manifest.by_key(k).workspace_id`, and the `publish-knowledge-docs` runner asserts
       `set(corpus_workspaces(manifest)) <= created`, raising `RuntimeError("404: ...")` on a
       miss. Run `cold_rebuild(..., apply=True, options=with_corpus(tmp_path))` and assert
       `report.passed`. Confirm it fails against the current order.
       Pre: none
       AC: #1
- [x] 4. Add `test_a_failed_domain_publish_never_reaches_the_corpus_step` to
       `tests/test_rebuild.py`: the `publish-domains` fake runner raises
       `GlobalmartError("publishing domain 'sales' failed: ...")`. Assert
       `pytest.raises(RebuildAbortedError, match="publish-domains")`, and that `calls` ends with
       `"publish-domains"` and never contains `"publish-knowledge-docs"` or `"verify"`.
       Pre: none
       AC: #5
- [x] 5. In `src/globalmart/rebuild.py`'s `_plan`, move the `corpus_step` block (the
       `RebuildStep(name="publish-knowledge-docs", ...)` construction and its two `SKIPPED`
       branches for `opts.skip_knowledge_docs` and a missing `opts.corpus_path`) from between
       `publish-parent` and `split` to after the `publish-domains` append and before the
       `if opts.verify:` block. Do not change the `SKIPPED` branch logic itself.
       Pre: task 1 complete, task 2 complete, task 3 complete, task 4 complete
       AC: #1, #2, #3
- [x] 6. Extend `_plan`'s corpus-step comment with one sentence: under
       `knowledge_scope: workspaces` the step writes into every workspace in
       `corpus_workspaces(manifest)`, and `publish_corpus`'s first call (`list_documents()`)
       does not tolerate a 404, so the step must run after `publish-domains` has created those
       workspaces — the ordering is deliberate, do not move the step earlier.
       Pre: task 5 complete
       AC: none (documentation)
- [x] 7. Reorder the `"publish-knowledge-docs"` entry in `step_runner`'s `runners` dict in
       `rebuild.py` to sit after `"publish-domains"`, so the dict reads in chain order. No
       behavioral effect — lookup only.
       Pre: task 5 complete
       AC: none (cosmetic)
- [x] 8. Update `rebuild.py`'s module docstring chain diagram: insert
       `-> publish the knowledge corpus` between `publish each child` and `verify the result`.
       Pre: task 5 complete
       AC: none (documentation)
- [x] 9. Run tasks 1–4's tests and confirm they now pass against the reordered `_plan`.
       Pre: task 5 complete, task 6 complete, task 7 complete, task 8 complete
       AC: #1, #2, #3, #5
- [x] 10. In `tests/test_rebuild.py`, replace `test_the_corpus_is_published_right_after_the_parent`
       with `test_the_corpus_is_published_only_after_the_domain_workspaces_exist`. Assert
       `names.index("split") < names.index("publish-domains") <
       names.index("publish-knowledge-docs")`, and that `publish-knowledge-docs` is immediately
       followed by `verify`. Its docstring states the real reason: `publish_corpus` does not
       tolerate a 404, and under `workspaces` scope it writes into every child.
       Pre: task 9 complete
       AC: #2
- [x] 11. In `tests/test_rebuild.py`, update `test_a_failed_corpus_publish_stops_the_chain` to
       additionally record `calls` and assert `"verify" not in calls`, locking in that the
       corpus step now sits before `verify` and still stops the chain on failure.
       Pre: task 9 complete
       AC: #1
- [x] 12. Add `test_skip_data_keeps_the_corpus_after_the_domains` to `tests/test_rebuild.py`:
       with `with_corpus(tmp_path, skip_data=True)`, assert the exact step list
       `["probe-org", "publish-parent", "split", "publish-domains", "publish-knowledge-docs",
       "verify"]`.
       Pre: task 9 complete
       AC: #2
- [x] 13. Add `test_a_skipped_corpus_step_keeps_its_place_in_the_report` to
       `tests/test_rebuild.py`: with `skip_knowledge_docs=True`, assert the `SKIPPED`
       `publish-knowledge-docs` step is still positioned immediately after `publish-domains` in
       `report.steps`.
       Pre: task 9 complete
       AC: #2
- [x] 14. ~~N/A: `organization` scope was removed (PR #13), so there is one scope and nothing to compare.~~ Add `test_the_plan_does_not_depend_on_knowledge_scope` to `tests/test_rebuild.py`:
       build the rehearsal twice, with `replace(profile(), knowledge_scope=KnowledgeScope.WORKSPACES)`
       and with `ORGANIZATION`, and assert the two `[s.name for s in report.steps]` lists are
       equal.
       Pre: task 9 complete
       AC: #4
- [x] 15. Re-run `test_every_step_carries_the_command_that_reproduces_it`,
       `test_every_planned_step_has_a_runner`, `test_a_failing_step_stops_the_chain`,
       `test_an_absent_corpus_is_a_named_skip_not_an_omission`,
       `test_skip_knowledge_docs_says_so_in_the_report`,
       `test_a_skipped_corpus_step_does_not_run_and_does_not_fail_the_chain`,
       `test_the_corpus_step_detail_names_the_scope`, and
       `test_a_failed_corpus_cleanup_fails_the_chain` unmodified, to confirm none of them assumed
       the old step order.
       Pre: task 10 complete, task 11 complete, task 12 complete, task 13 complete, task 14 complete
       AC: #4
- [x] 16. Run `uv run pytest` (full suite) and `globalmart rebuild --target <profile>` as a
       rehearsal (no `--apply`) to confirm the printed step order matches the new sequence.
       Pre: task 15 complete
       AC: #1, #2, #3, #4, #5
