# 010 — Where the knowledge corpus is published is a per-target setting

**Status:** Accepted (2026-09-28, after the probe below)
**Date:** 2026-09-25
**Context:** FEAT-015, FEAT-017; `knowledge_docs.py`, `rebuild.py`, `retrieval.py`, `config/targets.yaml`.
**Builds on** [ADR 009](009-two-ai-knowledge-channels.md), and revisits the one alternative it
rejected.

## Decision

Each target profile in `config/targets.yaml` gains `knowledge_scope`, with two values:

- `workspaces` (the default, and today's behaviour): the corpus is upserted into each of the
  thirteen GlobalMart workspaces.
- `organization`: the corpus is upserted **once** to `/api/v1/ai/organization/knowledge`, where
  every workspace in the org sees it.

ADR 009 rejected organization level for one reason: demo-cloud is a **shared** org, and GlobalMart
documentation would reach workspaces that have nothing to do with GlobalMart. That reason says
nothing about an org that holds only GlobalMart. There, organization level turns thirteen writes
into one, and a workspace created later sees the corpus with no extra publish step. Whether an org
is dedicated to GlobalMart is a fact about the target, not about the code, so it goes in the
profile (STEERING § "Config, not code"). demo-cloud stays on `workspaces`.

## Alternatives Considered

| Option | Pros | Cons |
|---|---|---|
| **Chosen: per-target `knowledge_scope`, default `workspaces`** | Bounded blast radius wherever the org is shared; one write where it is not; adding a dedicated org stays a config entry | Two publish paths to test; switching scope on a live target needs a migration (below) |
| Always `workspaces` (ADR 009 as it stands) | One code path; already built and verified | Thirteen writes per publish forever; a workspace added outside the manifest never gets the corpus |
| Always `organization` | Simplest publish | Wrong on demo-cloud: GlobalMart facts, such as "net revenue excludes intra-company transfers", would reach every other workspace in the org |
| Infer the scope, e.g. "org contains only `globalmart*` workspaces" | Nothing to configure | Silent behaviour change the day someone adds an unrelated workspace; a publish that widens its own blast radius must not decide that by itself |
| A real GoodData parent/child hierarchy, so documents inherit from `globalmart` | One write, scoped to GlobalMart | Contradicts ADR 001: domain workspaces are independent so each can be published into any org on its own |

## Consequences

- **Positive:** A dedicated org publishes the corpus with one API call, and new workspaces are
  covered without being listed.
- **Positive:** Nothing changes on demo-cloud or on any existing profile, because the key is
  optional and defaults to `workspaces`.
- **Neutral, ownership:** the ownership markers work unchanged. A document is ours if its
  filename starts with `gm-corpus__` **or** its scopes include `globalmart-corpus`, and
  `foreign_left_alone` protects other content at organization level exactly as it does in a
  workspace.
- **Neutral, prune:** pruning keeps its locality rule. Under `organization` the level being
  written is the organization (`workspace_id=None` in `knowledge_docs.py`), so only
  organization-level documents that are ours can be pruned. Workspace-level copies are never
  pruned by accident from the organization pass.
- **Trade-off, switching scope:** local documents outrank inherited ones. If a target moves from
  `workspaces` to `organization` and the thirteen workspace copies stay, those copies keep
  winning retrieval, and when they go stale they shadow the fresh organization copy. So a
  publish under either scope also removes our documents from the **other** level: under
  `organization` it deletes our workspace-level copies; under `workspaces` it deletes our
  organization-level copy. This runs only with `--apply`, and a dry run lists it as a planned
  deletion (ADR 002). `verify --prune` checks both levels.
- **Trade-off, retrieval:** `retrieval.py` searches **from a workspace**
  (`/workspaces/{ws}/knowledge/search`), which returns organization-level chunks. So the
  assertions work unchanged under `organization`. It must still search from a real GlobalMart
  workspace, and a hit must be matched by filename, not by where the document is stored.
- **Trade-off, CLI:** under `organization`, `--parent-only` and `--workspace-id` have no meaning.
  Passing either is an error that names the target's scope, not a silent no-op.
- **Neutral, rebuild:** the `publish-knowledge-docs` step in `rebuild.py` reads the scope from
  the same profile, and its report states which scope it used.

## Revisit Trigger

- The Python SDK or the declarative layout starts modelling knowledge documents. Publishing then
  belongs in the layout, and this setting and `knowledge_docs.py` should be reconsidered
  together.
- A GlobalMart org becomes shared with other content while set to `organization`. Switch it back
  to `workspaces`; the cleanup rule above handles the move.
- GoodData adds a scope between workspace and organization (for example, a workspace group) that
  GlobalMart's independent workspaces can join without a parent/child hierarchy.

## Probe findings — 2026-09-25

`scripts/probe_org_knowledge.py` against demo-cloud (`gm-ddebmti`). The write half put one
document at organization level (`gm-probe__org-level.md`, no ownership marker, one chunk),
approved for this shared org because it was harmless and lived for seconds. It ran twice and
was deleted in a `finally` both times.

| # | Question | Answer |
|---|---|---|
| P1 | Does `/api/v1/ai/organization/knowledge/documents` behave like the workspace endpoint? | Yes. The listing returns `documents` and `totalCount`. `PUT` returns the same upsert body (`id`, `filename`, `success`, `message`, `numChunks`). `DELETE {id}` works. Ids are deterministic per filename: both runs got the same id |
| P2 | What `workspaceId` does an org-level document report? | `null`, both in the org listing and in a workspace listing. The workspace listing includes it, so `is_local_to(None)` is the right locality test |
| P3 | Does the org listing include workspace-level documents? | No. It returned 1 document while `globalmart` held 33 |
| P4 | Does a workspace search return org-level chunks? | Yes, first attempt, no extra parameter, with `workspaceId: null`. `retrieval.py` needs no change |
| P5 | Can this token read the org level? | Yes. The 403 path is untested live and handled per D1 below |

## Decisions taken while building (FEAT-017)

- **D1, org level unreadable under the default scope.** A 403 on the organization listing under
  `workspaces` is reported as a named `SKIPPED` line, and the publish still passes. A token that
  cannot read that level cannot have written our copy there. Under `organization`, a 403 fails
  as usual. A 404 on any level means "nothing to clean" under both scopes.
- **D2, where the P4 write ran.** On demo-cloud, with the exposure explicitly accepted. This does
  not change the rule for a shared org: the corpus itself never goes to organization level there.
- **Partial cleanup** exits non-zero with a full per-level report (CONTRACT § Errors: no partial
  success reported as success). It is not a softer "partial success" state.
