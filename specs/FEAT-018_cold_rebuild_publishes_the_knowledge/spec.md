---
abandoned_at: null
abandoned_reason: null
appetite: xs
blocked_at: null
blocked_by: null
confidence: high
created: '2026-09-29'
cycle: null
depends_on:
- feat-017
enables: []
goal: goal-01
id: feat-018
links: []
name: 'Cold rebuild publishes the knowledge corpus before the domain workspaces exist:
  move publish-knowledge-docs after publish-domains so a fresh-org rebuild under knowledge_scope:
  workspaces does not hit twelve 404s'
sources: []
status: done
tags: []
updated: '2026-10-24'
---

## Summary

`rebuild.py`'s step chain runs `publish-knowledge-docs` immediately after `publish-parent` and
before `publish-domains`, on the reasoning (now stale) that children "inherit it at query time."
FEAT-017 replaced that with explicit per-workspace writes under `knowledge_scope: workspaces` —
the default — and `publish_corpus` calls `api.list_documents()` with no 404 handling. Against a
workspace that does not exist yet, that call raises `KnowledgeDocsError` uncaught, which
propagates through `publish_for_target` and fails the whole `publish-knowledge-docs` step before
`publish-domains` has even run. A cold rebuild into a fresh org therefore cannot finish: goal-01's
"a clean clone plus credentials rebuilds ... with no manual step" is broken at the one path that
proves it. Confirmed by reading `rebuild.py`'s step order and `publish_corpus`'s body while
building FEAT-017; not yet reproduced against a live fresh org, only against the code. The fix is
a reorder, not new logic: move `publish-knowledge-docs` after `publish-domains` in both the step
list and `_plan`'s ordering, so every level it writes to already exists. Under
`knowledge_scope: organization` the bug does not reproduce (the single write is to the
organization level, which always exists), but the step still belongs after domain creation for
consistency and because a future scope value might write per-workspace again.

## Appetite
`xs` — < 1 day

## Acceptance Criteria
- [ ] Given a fresh org with no domain workspaces yet, when `globalmart rebuild --apply` runs
      under the default `knowledge_scope: workspaces`, then `publish-domains` completes before
      `publish-knowledge-docs` runs, and the corpus step upserts into all twelve domain
      workspaces successfully rather than 404ing.
- [ ] Given the reordered chain, when `cold_rebuild`'s `_plan` lists steps for a rehearsal, then
      the printed order is `..., publish-parent, split, publish-domains,
      publish-knowledge-docs, verify` (or equivalent — `split` must precede `publish-domains`,
      which must precede `publish-knowledge-docs`).
- [ ] Given the existing `test_a_rehearsal_plans_every_step_and_runs_none` step-order assertion
      in `tests/test_rebuild.py`, when it is updated for the new order, then it still asserts a
      complete, exact step sequence (not a subset check) so a future reorder is caught the same
      way this one was found.
- [ ] Given `knowledge_scope: organization`, when the reordered chain runs, then behavior is
      unchanged from before this fix (the org level exists regardless of domain-workspace state).
- [ ] Given the corpus step now depends on `publish-domains` having actually created the
      workspaces (not just having run), when `publish-domains` is skipped or fails, then
      `publish-knowledge-docs` does not silently upsert into workspace ids that were never
      created — it should fail loudly with the same "no partial success" rule FEAT-017 applied
      to cleanup, not produce a misleading 404 buried in a stack trace.

## Scope
- Reorder `RebuildStep` registration and `_plan`'s step list in `rebuild.py`: `split` and
  `publish-domains` before `publish-knowledge-docs`.
- Update the corpus step's `RebuildStep` docstring/comment (FEAT-017 already corrected the
  "children inherit it at query time" claim; the remaining stale assumption is the ordering
  rationale, not the wording).
- Update `tests/test_rebuild.py`'s step-order assertion(s) to the new sequence.
- Re-run the existing `_plan`-only rehearsal tests to confirm nothing else assumed the old order
  (e.g. a `--skip-knowledge-docs` or `--skip-data` interaction that implicitly relied on the
  corpus step running early).

## Out of Scope
- Any change to `knowledge_docs.py`'s publish/cleanup logic itself — FEAT-017 already built
  `publish_for_target`, `remove_ours`, and the 403/404 handling `remove_ours` uses for cleanup.
  This feature only fixes where in the chain that logic is invoked.
- Making `publish_corpus`'s initial `list_documents()` call tolerate a 404 the way `remove_ours`
  does. Reordering removes the precondition that causes the 404 in the first place; teaching the
  write path to shrug off "workspace doesn't exist" would hide a genuinely different failure
  (e.g. a typo'd workspace id) behind a soft skip.
- A live fresh-org rebuild run to reproduce and confirm the fix — appetite `xs` does not cover
  standing up a new org. The reorder is validated by the reworked `test_rebuild.py` assertions and
  by re-running the CI gate's existing rehearsal tests.

## Key Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Some other step implicitly relies on `publish-knowledge-docs` running right after `publish-parent` (e.g. a `verify` step reading knowledge state before domains are split) | low | medium — a reorder that fixes one path breaks another | Re-run the full rehearsal test suite after reordering, not just the step-order assertion; grep for any other reference to step position |
| The fix is validated only against fakes/rehearsals, not a real fresh org | medium | low — the bug itself was found by code reading, not a live failure, so the fix carries the same confidence level | Note in Related Research; a live fresh-org rebuild remains the eventual proof of goal-01's measurable outcome, tracked separately, not blocked on this xs fix |

## Dependencies
- **Depends on:** FEAT-017 (introduced the per-workspace `publish_for_target` write path this
  bug is in; the corpus step's prior FEAT-015 form published to the parent only, so this
  ordering bug did not exist before FEAT-017).
- **Enables:** a genuine cold-rebuild-into-a-fresh-org proof for goal-01, currently blocked by
  this ordering.

## Related Research
- Found while building FEAT-017 (breakdown.md's Integration Points section, "Observed while
  reading, and out of scope here"): `rebuild.py`'s `publish-knowledge-docs` step runs between
  `publish-parent` and `split`/`publish-domains`.
- `src/globalmart/knowledge_docs.py`'s `publish_corpus`: the first call is `api.list_documents()`
  with no status-code handling, unlike `remove_ours` (FEAT-017), which explicitly treats a 404
  listing as `absent=True` rather than a failure.
- No sources have been enriched for this feature (`meridian search` returned no hits).

## Open Questions
- Should `publish_corpus`'s write path eventually gain the same 404-tolerant behavior as
  `remove_ours`, so a not-yet-created workspace is a named skip rather than a hard failure
  regardless of step order? Left out of scope here because the reorder is the more direct fix
  and a silently-skipped write is a worse failure mode than a loud one — but worth revisiting if
  another step-ordering dependency surfaces later.
