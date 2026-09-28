## Tasks — FEAT-017: Per-target `knowledge_scope` for the AI Knowledge corpus

> Appetite: `s`  ·  Generated: 2026-09-25

- [x] 1. Write `scripts/probe_org_knowledge.py`, styled like `scripts/take_custody.py`: a one-shot,
       unregistered script that runs read-only `GET`s for P1–P3 and P5 (org listing, one workspace
       listing, and the permission/404 shape of each against `/api/v1/ai/organization/knowledge`).
       The P4 write half (upload `gm-probe__org-level.md`, no ownership marker, search from a
       workspace, delete in `finally`) runs only behind `--apply`. Prints a findings block.
       Pre: none
       AC: #9
- [x] 2. [DECISION NEEDED: D2 — which org the P4 write runs against] Run the C0 probe's read-only
       half (P1–P3, P5) against demo-cloud or another available org, and record the findings block
       in this task's commit message or a scratch note.
       Pre: task 1 complete
       AC: #9
- [x] 3. [DECISION NEEDED: D1 — behavior when org-level is unreadable under `workspaces` scope]
       Decide the 403-vs-404 handling described in breakdown.md's D1, using P5's findings from
       task 2. Record the decision in ADR 010's amendments (task 15) rather than re-litigating it
       later.
       Pre: task 2 complete
       AC: #1
- [x] 4. With D2 answered, run the C0 probe's `--apply` half (P4: throwaway org-level document,
       search from a workspace, delete). Record whether workspace search surfaced the org-level
       chunk. **Gate:** if it did not, stop — `retrieval.py` needs a design change and AC 7's
       premise fails; revise the spec before continuing.
       Pre: task 3 complete (D1/D2 both answered)
       AC: #7, #9
- [x] 5. Amend CONTRACT.md: add the `TargetProfile.knowledge_scope` row, a `KnowledgeScope`
       paragraph (shaped like `WarehouseType`'s), widen the `knowledge_docs.py` row to cover
       `/api/v1/ai/{workspaces/{id}|organization}/knowledge/...`, mark the on-disk
       `docs/knowledge-corpus/` row scope-dependent, qualify the `AiSelection.knowledge_ids`
       paragraph, and add `(+017)` to the `Feature` column on `knowledge-docs publish`, `verify`
       and `rebuild` rows. No CLI flag changes.
       Pre: task 4 complete
       AC: #1, #2, #3
- [x] 6. Add `KnowledgeScope` (`StrEnum`: `WORKSPACES` default, `ORGANIZATION`) and the
       `TargetProfile.knowledge_scope` field to `config.py`. Parse it in `load_profile` from the
       YAML entry only, no environment override; raise `GlobalmartError` naming supported values
       on an unknown entry.
       Pre: task 5 complete
       AC: #1
- [x] 7. Write tests in `test_config.py`: default-when-absent, organization value parsed, unknown
       value raises with both supported values named, and an env var (`GLOBALMART_KNOWLEDGE_SCOPE`)
       is ignored.
       Pre: task 6 complete
       AC: #1
- [x] 8. Add `ORGANIZATION_BASE` to `knowledge_docs.py`. Change `HttpKnowledgeApi.workspace_id` to
       `str | None`, add `for_organization(profile)` classmethod, make `base` switch on `None`,
       make `search()` raise `KnowledgeDocsError` when called at organization level, and add
       `status: int | None` to `KnowledgeDocsError`, set from `HTTPError.code` in `_request`.
       Pre: task 6 complete
       AC: #2, #9
- [x] 9. Write tests in `test_knowledge_docs.py`: organization level addresses
       `ORGANIZATION_BASE`, `for_organization` sets `workspace_id=None`, and `search()` at
       organization level is refused.
       Pre: task 8 complete
       AC: #2
- [x] 10. Change `publish_corpus`, `verify_corpus` and `_partition` to accept `workspace_id:
       str | None`, where `None` means organization level. Add `KnowledgeDocsReport.level_label`
       property. Confirm the full existing FEAT-015 test suite still passes unchanged (proves the
       change is behavior-neutral for `str` levels).
       Pre: task 8 complete
       AC: #1, #6
- [x] 11. Write tests in `test_knowledge_docs.py`: publishing at organization level
       (`workspace_id=None`) treats null-workspace remote documents as local, detects `unchanged`
       on a second run, and detects orphans.
       Pre: task 10 complete
       AC: #6
- [x] 12. Implement `remove_ours(api, *, workspace_id, apply) -> CleanupReport` in
       `knowledge_docs.py`: lists one level, selects documents that are `is_ours()` and
       `is_local_to(level)`, deletes (or plans, if not `apply`) every one of them, records failures
       per document and continues, and treats a 404 listing as `absent=True` rather than a failure.
       Add the `CleanupReport` dataclass.
       Pre: task 10 complete
       AC: #4, #5, #6
- [x] 13. Extend `FakeKnowledgeApi` in `test_knowledge_docs.py` with a `level: str | None` field
       used by `upsert_document`/`list_documents` in place of a hard-coded workspace, and add a
       `FakeOrg` (`dict[LevelId, FakeKnowledgeApi]`) whose `__call__(level)` acts as an
       `ApiFactory`.
       Pre: task 12 complete
       AC: #4, #5, #6
- [x] 14. Write tests in `test_knowledge_docs.py` for `remove_ours`: a foreign document (no
       ownership marker) at either level is never touched and appears in `foreign_left_alone`; an
       absent (404) level is a clean no-op, not a failure; a rehearsal (`apply=False`) plans
       deletions and issues none.
       Pre: task 13 complete
       AC: #4, #5, #6
- [x] 15. Add `ScopedCorpusReport` and `corpus_workspaces(manifest)` to `knowledge_docs.py`
       (the latter replacing the duplicated workspace-list logic in `cli.py` and `rebuild.py`).
       Implement `publish_for_target(profile, documents, *, workspaces, narrowed, apply,
       api_factory=None)`: writes every configured level via `publish_corpus`, then — only if
       every write succeeded — cleans the other level(s) via `remove_ours`; a narrowed publish
       (`--parent-only` / `--workspace-id` under `workspaces`) never cleans the organization level
       and sets `cleanup_deferred`. Apply the D1 decision from task 3 for a 403 on the org-level
       listing under `workspaces` scope.
       Pre: task 14 complete
       AC: #1, #2, #4, #5
- [x] 16. Write tests in `test_knowledge_docs.py` for `publish_for_target`: default scope writes
       all 13 workspace levels and touches organization not at all; organization scope writes
       exactly one level and touches no workspace; moving to `organization` removes workspace
       copies in the same run; moving to `workspaces` removes the organization copy in the same
       run; cleanup is skipped when a write failed, with `cleanup_deferred` naming the level; a
       partial cleanup failure (one of 13 levels) fails loudly, cleans the other 12, and names
       what remains; a narrowed publish never cleans the organization level; the D1 behavior for a
       403 on org-level listing under `workspaces` scope.
       Pre: task 15 complete
       AC: #1, #2, #4, #5
- [x] 17. Implement `verify_for_target(profile, documents, *, workspaces, narrowed, prune, apply,
       api_factory=None) -> ScopedCorpusReport`: reconciles the configured level(s) via
       `verify_corpus`, prunes only at those level(s), and reports any of our documents found at
       the *other* level as `other_level_ours` (stale, makes the result non-zero) without deleting
       them.
       Pre: task 15 complete
       AC: #6
- [x] 18. Write tests in `test_knowledge_docs.py` for `verify_for_target`: prune under
       `organization` deletes only organization-level orphans, never a workspace-level document or
       a foreign one; a workspace-level copy of ours under `organization` scope is reported as
       `other_level_ours` and marks the result stale.
       Pre: task 17 complete
       AC: #6
- [x] 19. Add `check_scope_flags(profile, *, parent_only, workspace_id) -> None` to
       `knowledge_docs.py`, raising `KnowledgeScopeError(KnowledgeDocsError)` when either flag is
       set under `organization` scope, naming the target, its scope, and the offending flag.
       Pre: task 6 complete
       AC: #3
- [x] 20. Write a test in `test_knowledge_docs.py`: `check_scope_flags` rejects `--parent-only` and
       `--workspace-id` under `organization`, accepts both under `workspaces`, and the message
       names the target and scope.
       Pre: task 19 complete
       AC: #3
- [x] 21. Rewire `cmd_knowledge_docs_publish` and `cmd_knowledge_docs_verify` in `cli.py` to call
       `check_scope_flags` before any network call, then delegate to `publish_for_target` /
       `verify_for_target` and print `ScopedCorpusReport.summary_lines()`. Shrink
       `_corpus_workspaces` to arg-narrowing only, over `knowledge_docs.corpus_workspaces`.
       Leave `cmd_knowledge_docs_retrieval` unchanged.
       Pre: task 19 complete, task 17 complete
       AC: #1, #2, #3, #4, #5, #6
- [x] 22. Write tests in `test_cli.py`: publish/verify under `organization` scope rejects
       `--parent-only` and `--workspace-id` with a non-zero exit and a message naming the scope,
       and no API client is constructed when rejected (monkeypatch `HttpKnowledgeApi` to raise if
       built).
       Pre: task 21 complete
       AC: #3
- [x] 23. Update `rebuild.py`'s `_run_publish_knowledge_docs` to call `publish_for_target(...,
       narrowed=False, apply=True)` in place of its own workspace loop. Raise `GlobalmartError` on
       a write failure (unchanged) or a cleanup failure (new). The detail string leads with the
       scope used. SKIPPED paths and their details are unchanged. Correct the stale
       "children inherit it at query time" comment.
       Pre: task 15 complete
       AC: #8
- [x] 24. Write tests in `test_rebuild.py`: the `publish-knowledge-docs` detail names the scope
       under both `workspaces` and `organization`; the no-corpus and `--skip-knowledge-docs` SKIP
       paths are unchanged; a cleanup failure fails the chain (raises `GlobalmartError`, is not
       swallowed).
       Pre: task 23 complete
       AC: #8
- [x] 25. Write a test in `test_retrieval.py`: a `SearchResult` with `workspace_id=None` (an
       organization-level hit) satisfies a retrieval question — matching is by filename, not by
       where the document is stored.
       Pre: task 4 complete (P4 confirmed)
       AC: #7
- [x] 26. Update `config/targets.yaml`: add explicit `knowledge_scope: workspaces` to `demo-cloud`
       and `demo-cloud-rebuild` with a comment noting the shared org and ADR 009/010. Add a
       commented `knowledge_scope: organization` example profile with a note that it applies only
       to an org dedicated to GlobalMart. Leave `usecases-ai` (or another existing profile) without
       the key so the default path stays exercised.
       Pre: task 6 complete
       AC: #1
- [x] 27. Update the `knowledge_docs.py` module docstring's endpoint table with the
       organization-level rows and the probe verification date from task 2/4. Update ADR 010's
       status from Proposed to Accepted, appending the probe findings (P1–P5) and the D1/D2
       decisions.
       Pre: task 24 complete, task 25 complete
       AC: #9
- [x] 28. Run the full test suite and CI gate checks (ruff, mypy, pytest) to confirm no regression
       in the existing FEAT-015 knowledge-docs behavior.
       Pre: task 27 complete
       AC: #1
