---
abandoned_at: null
abandoned_reason: null
appetite: s
blocked_at: null
blocked_by: null
confidence: medium
created: '2026-09-25'
cycle: null
depends_on:
- feat-015
enables: []
goal: goal-01
id: feat-017
links: []
name: 'Per-target knowledge_scope for the AI Knowledge corpus: publish into every
  GlobalMart workspace (default) or once at organization level for orgs dedicated
  to GlobalMart, set per profile in targets.yaml, with cross-level cleanup on a scope
  switch — implements ADR 010'
sources: []
status: in-progress
tags: []
updated: '2026-09-25'
---

## Summary

FEAT-015 built the AI Knowledge corpus and publishes it into all thirteen GlobalMart workspaces
(one upsert each) because ADR 009 found no real GoodData workspace hierarchy to inherit through
and rejected organization-level publish for demo-cloud, a shared org where GlobalMart content
would leak into unrelated workspaces. [ADR 010](../decisions/010-knowledge-scope-per-target.md)
revisits that one rejection for the case it doesn't cover: an org used *only* for GlobalMart,
where a single organization-level upsert replaces thirteen and any workspace added later is
covered automatically, with no manifest update. This feature implements ADR 010: a
`knowledge_scope` key per profile in `config/targets.yaml` (`workspaces` default, `organization`
opt-in), the org-level publish/list/prune path in `knowledge_docs.py` (today the module only
talks to `/api/v1/ai/workspaces/{ws}/knowledge/...` — the organization endpoint does not exist
in code yet), and cleanup of the level being abandoned when a target's scope changes, since a
local document always outranks an inherited one and a stale local copy would shadow a fresh
organization one. This keeps goal-01's "rebuild into any org is a config entry, never a code
change" promise intact for orgs dedicated to GlobalMart.

## Appetite
`s` — 1–3 days

## Acceptance Criteria
- [ ] Given a target profile with no `knowledge_scope` key, when `knowledge-docs publish` runs,
      then behavior is unchanged from today: one upsert per workspace, in all thirteen.
- [ ] Given a target profile with `knowledge_scope: organization`, when `knowledge-docs publish
      --apply` runs, then exactly one upsert is made to the organization-level endpoint and none
      to any workspace.
- [ ] Given `knowledge_scope: organization`, when `--parent-only` or `--workspace-id` is passed,
      then the CLI exits with an error naming the target's scope, not a silent no-op.
- [ ] Given a target moved from `workspaces` to `organization`, when publish runs with `--apply`,
      then our documents (by ownership marker) are removed from all thirteen workspaces in the
      same run that writes the organization copy — never left to shadow it.
- [ ] Given a target moved from `organization` to `workspaces`, when publish runs with `--apply`,
      then our organization-level copy is removed in the same run that writes all thirteen
      workspace copies.
- [ ] Given `knowledge_scope: organization`, when `verify --prune` runs, then it lists and (with
      `--apply`) deletes only our documents that are local to the organization level — never a
      workspace-level document, and never a foreign one (ownership markers still decide, per
      ADR 009).
- [ ] Given `knowledge_scope: organization`, when `retrieval.py`'s checks run against a real
      GlobalMart workspace, then the expected document is found within `limit` and its expected
      facts appear in the returned chunks — searching from a workspace must surface
      organization-level documents.
- [ ] Given `knowledge_scope: organization`, when `rebuild.py`'s `publish-knowledge-docs` step
      runs, then its report states the scope used and the step's pass/fail semantics from ADR
      009 (skip named when no corpus, fail the chain on a real publish failure) are unchanged.
- [ ] Given the organization-level publish/list/delete calls, when exercised read-only against a
      real org (the precondition probe below), then the endpoint shapes assumed by ADR 009/010
      are confirmed or the spec is revised before `--apply` code is written.

## Scope
- `knowledge_scope: workspaces | organization` in `config/targets.yaml`, default `workspaces`
  when the key is absent (no migration needed for existing profiles).
- Organization-level REST calls in `knowledge_docs.py`: upsert, list, download, delete against
  `/api/v1/ai/organization/knowledge/documents` (path per ADR 009's "worth revisiting" note —
  confirm exact shape in the precondition probe), mirroring the existing workspace-scoped
  `HttpKnowledgeApi` methods.
- `publish_corpus` / `verify_corpus` parameterized so `workspace_id=None` addresses the
  organization level, consistent with `RemoteDocument.is_local_to`'s existing `None` handling
  for inherited documents.
- Cross-level cleanup: a scope-aware publish path that, in addition to writing the configured
  level, removes our documents from the *other* level in the same `--apply` run.
- CLI validation in `cmd_knowledge_docs_publish` / `cmd_knowledge_docs_verify`: reject
  `--parent-only` / `--workspace-id` under `organization` scope with a named error.
- `rebuild.py`'s `publish-knowledge-docs` step reads and reports the scope.
- A read-only precondition probe against a real org (or a fresh throwaway one) before any
  `--apply` code lands: confirm the organization-level endpoint exists and behaves like the
  workspace one, and confirm a workspace-level `GET .../knowledge/search` actually returns
  organization-level chunks (ADR 009 asserts this from documentation, not from a probe of this
  specific relationship).

## Out of Scope
- Changing demo-cloud's scope — it stays `workspaces` (ADR 009's reasoning for a shared org is
  unchanged).
- Any in-layout representation of knowledge documents (`AiSelection.knowledge_ids` stays
  dormant, per ADR 009).
- A third scope value (e.g. a GoodData workspace group), tracked only as ADR 010's revisit
  trigger.
- Automatic detection of whether an org is "dedicated" to GlobalMart — this stays an explicit,
  human-set config value, never inferred from org contents.

## Key Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Organization-level endpoint doesn't exist, or its shape differs from the workspace one (paths, payload fields, pagination) | medium | high — blocks the whole feature | Run the read-only precondition probe first; treat it as a spike gate before writing `--apply` code, same discipline as ADR 009's own probe |
| Workspace-level search does not actually surface organization-level chunks | medium | high — breaks retrieval.py's acceptance criterion and the assistant's actual behavior | Same probe, second half: publish one throwaway doc at org level and search for it from a workspace before relying on it |
| Cross-level cleanup deletes the wrong thing (e.g. a workspace-local document a colleague uploaded that happens to collide in filename) | low | high — data loss on someone else's content | Ownership markers (filename prefix or scope) gate every delete, unchanged from ADR 009; test with a foreign document present at both levels |
| A scope switch is applied without cleanup running (e.g. `--apply` fails partway) | medium | medium — stale local copy shadows the new organization copy, silently wrong answers | Report explicitly lists what was and wasn't cleaned up; `verify --prune` catches leftovers on a later run |

## Dependencies
- **Depends on:** FEAT-015 (built the corpus and the workspace-scoped publish/verify/retrieval
  path this extends), ADR 009, ADR 010.
- **Enables:** nothing currently queued; positions goal-02's demo work to use a
  GlobalMart-dedicated org with a single knowledge publish, if one is ever stood up.

## Related Research
- [ADR 009](../decisions/009-two-ai-knowledge-channels.md) — why the corpus lives outside the
  layout, why it's published per-workspace today, and why organization level was rejected for a
  shared org (with the "worth revisiting" note this feature acts on).
- [ADR 010](../decisions/010-knowledge-scope-per-target.md) — the decision this feature
  implements, including the alternatives considered and the cross-level cleanup rule.
- `src/globalmart/knowledge_docs.py` — current implementation: `HttpKnowledgeApi` only knows
  `WORKSPACE_BASE`; `RemoteDocument.is_local_to` already treats a `None` workspace id as
  "organization level" for documents *read* by a workspace listing, but nothing today *writes*
  to the organization level.
- No sources have been enriched for this feature yet (`meridian search` returned no hits). If a
  design doc or org API reference exists, add it with `meridian enrich feat-017 <source>` before
  `/breakdown`.

## Open Questions
- What is the exact path and payload shape of the organization-level knowledge endpoint? ADR 009
  names `/api/v1/ai/organization/knowledge` from documentation; unconfirmed against a real org.
- Does `GET /workspaces/{ws}/knowledge/search` merge organization-level results by default, or
  does it need a parameter? Affects whether `retrieval.py` needs any change at all versus none.
- When cleanup fails partway (org write succeeds, workspace cleanup fails on workspace 7 of 13),
  should the run report a hard failure or a partial-success state that `verify` is expected to
  finish? Leaning partial-success with a loud report, matching ADR 009's "named SKIPPED rather
  than absent" philosophy, but not yet decided.
