---
abandoned_at: null
abandoned_reason: null
appetite: m
blocked_at: null
blocked_by: null
confidence: medium
created: '2026-09-18'
cycle: null
depends_on:
- feat-001
- feat-002
enables:
- feat-004
goal: goal-01
id: feat-008
name: 'Knowledge ingestion: compile authored Markdown documents into AI memory items
  in the parent workspace, chunked by section, so domain knowledge travels cross-org
  with the layout'
sources: []
status: done
tags: []
updated: '2026-09-20'
---

## Summary

GlobalMart's AI assistant has no domain knowledge beyond what the semantic layer names. Nothing
tells it that net revenue excludes intra-company transfers, that the fiscal year starts in February,
or which of two similarly named metrics an analyst actually means. That knowledge exists in people's
heads and in documents, and there is no path from a document into the workspace.

This feature builds that path: you author Markdown under `docs/knowledge/`, and a build step
compiles it into AI memory items inside the captured parent layout — one item per document section,
with keywords derived from headings so retrieval returns the relevant slice rather than the whole
document. Because the memory items land in the layout tree, they are captured, versioned, published
and domain-split by machinery that already exists: FEAT-001 counts them, FEAT-002 publishes them to
any org, FEAT-004 filters them per domain.

**There is no document-upload API.** The GoodData API models no knowledge document and no file
ingestion — searched both the API client and gdc-nas. So "uploading a document" means compiling it
into memory items. Naming it anything else would promise a capability the platform does not have.

### Where knowledge lands — verified against the live org, 2026-09-18

Confirming the user's instinct that this is not an LDM concern:

- `GET /api/v1/layout/workspaces/globalmart` returns exactly two top-level keys, `ldm` and
  `analytics`. **`memoryItems` sits under `analytics`, not `ldm`** — knowledge is analytics-layer
  content, so nothing here touches the semantic model.
- `GET /api/v1/entities/workspaces/globalmart/memoryItems` → `200`, **0 items**. The channel is live
  and empty.
- `GET /api/v1/entities/workspaces/globalmart/knowledgeRecommendations` → `200`, 0 items. Narrow,
  metric-bound objects; not general knowledge.
- `.../agents` → **`404` at workspace scope**. Agent personalities live in the *organization* layout
  (`GET /api/v1/layout/organization` carries an `agents` key), which FEAT-001 does not capture — see
  Out of Scope.

**And it is copied locally**, through machinery that already exists. Round-tripped a real memory item
through `write_tree` to confirm the path and shape:

```
layouts/workspaces/globalmart/analytics_model/memory_items/<id>.yaml

  id: probe_net_revenue
  instruction: Net revenue excludes intra-company transfers.
  keywords: [revenue, net]
  strategy: AUTO          # enum: ALWAYS | AUTO — required, no default
  tags: [domain/finance]
  title: Net Revenue
```

So the compiled output lands beside every other captured object, is normalized and byte-stable by
FEAT-001's writer, publishes through FEAT-002 with no new code path, and is filterable per domain by
FEAT-004 via `tags`. `strategy` is a required enum (`ALWAYS` or `AUTO`) with no default — the
compiler must set it explicitly, and it is worth exposing per document since it decides whether an
item is always injected or retrieved on relevance.

## Appetite

`m` — 1–2 weeks

## Acceptance Criteria

- [x] Given a Markdown file under `docs/knowledge/`, when `globalmart knowledge build` runs, then one
      memory item is emitted per second-level section, written into
      `layouts/workspaces/globalmart/analytics_model/memory_items/`, with a deterministic id derived
      from the file and heading.
- [x] Given the same source documents run twice, when the build completes, then `git diff` is empty —
      the emitted items are byte-stable, and `globalmart normalize --check` still reports the tree
      canonical.
- [x] Given a section heading and body, when the item is emitted, then `title` is the heading,
      `instruction` is the body text, and `keywords` contains terms drawn from the heading plus any
      explicit `keywords:` front-matter, so retrieval has something to match on.
- [x] Given a section removed from a source document, when the build re-runs, then its memory item is
      deleted from the tree rather than left orphaned (the same guarantee `write_tree` gives).
- [x] Given a document with domain front-matter (`domains: [finance, sales]`), when the item is
      emitted, then it carries matching `tags`, so FEAT-004's per-domain AI filtering can select it
      without a second mapping file.
- [x] Given a built tree, when it is published with FEAT-002, then the memory items appear in the
      target org, and a second publish reports no change.
- [x] Given a section whose body exceeds a configured size limit, when the build runs, then it fails
      naming the file and heading rather than silently emitting an item too large to be useful.
- [x] Given a hand-edited memory item YAML, when the build re-runs, then the hand edit is overwritten
      — the Markdown is the source of truth, and `docs/knowledge/` is the only place to change
      content.

## Scope

- `docs/knowledge/*.md` — authored source documents, with optional YAML front matter for
  `domains`, `keywords` and `strategy`.
- A section-level chunker: split on `##` headings, carry the document title as context.
- Deterministic id generation (`<file-stem>_<heading-slug>`), so ids are stable across builds and
  reviewable in a diff.
- `globalmart knowledge build [--check]` — compiles into the layout tree; `--check` exits 1 if the
  tree would change, matching the existing CI gate convention.
- Emission into the existing `memory_items` channel of the captured layout, so no new publish path,
  no new capture path and no new config are needed.
- A guard that a knowledge build never disturbs non-knowledge objects in the tree.

## Out of Scope

- **Any file-upload API.** None exists. If one appears, revisit — the chunker would then feed it
  instead of the memory-item channel.
- Embedding generation, vector storage or retrieval tuning. The platform owns retrieval; this
  feature owns getting content in.
- PDF, DOCX or HTML ingestion. Markdown only; converting other formats is a separate concern and
  loses structure in ways that need their own decisions.
- Org-level memory items (`org_memory_item`). Workspace-scoped only, so knowledge travels with the
  workspace rather than being a property of the org.
- **Agent personalities.** Verified 2026-09-18 that `agents` is an *organization*-layout key and
  returns 404 at workspace scope, so capturing them means capturing the org layout — which
  FEAT-001 deliberately does not do. That is a real gap in cross-org portability (a published
  GlobalMart arrives with no agents), but it is org-level work, not knowledge ingestion. Worth its
  own feature.
- `knowledge_recommendation` objects — metric-bound, generated rather than authored.
- Authoring the actual GlobalMart knowledge content. This feature ships the mechanism plus one small
  worked example; writing the glossary is domain work.

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Section-level chunks are the wrong granularity — too coarse to retrieve precisely, too fine to carry context | Medium | Medium | Start at `##`, make the split level configurable, and ship one real document early so the granularity is judged against actual assistant behaviour rather than guessed |
| Memory items are untested territory: GlobalMart has zero today, so nothing proves the assistant uses them as expected | High | Medium | Publish a handful to a workspace and ask the assistant a question only the document answers, before building volume |
| Knowledge and the captured layout fight over the same tree — a re-capture could wipe generated items | Medium | High | `bootstrap` and `knowledge build` both write the tree; the build must run after capture, and a test must prove a capture-then-build cycle converges. This ordering needs to be explicit in the CLI and documented |
| Keywords derived from headings are too thin for retrieval to match real questions | Medium | Medium | Allow explicit `keywords:` front matter to override; treat the derived set as a default, not the mechanism |
| Content drifts from the semantic layer it describes (a metric is renamed, the document is not) | Medium | Medium | Out of scope to solve here, but FEAT-006 could later assert that every metric named in a knowledge document exists in the LDM |

## Dependencies

- **Depends on:** feat-001 (`layout_io.write_tree`, the captured tree, the `memory_items` channel and
  the SDK floor that models it), feat-002 (publishing the result to an org).
- **Enables:** feat-004 — per-domain AI filtering has something to filter; today the AI channels are
  empty, so that machinery is untested against real content.

## Related Research

- API surface checked 2026-09-18: `json_api_memory_item_*` and `json_api_org_memory_item_*` exist
  with attributes `title`, `description`, `instruction`, `keywords`, `tags`, `strategy`,
  `is_disabled`, `are_relations_valid`. No knowledge-document or file-upload model exists in the API
  client, and `knowledge` appears nowhere in gdc-nas.
- `CatalogDeclarativeAnalyticsLayer.memory_items` exists only from gooddata-sdk 1.74 — pinned and
  asserted by `tests/test_sdk_floor.py` during FEAT-001.
- GlobalMart currently carries 0 memory items and 0 parameters, so this feature creates the first
  real content in those channels.
- STEERING § Portability Contract: AI context is first-class versioned content that must survive a
  cross-org publish; the splitter must filter it per domain.

## Open Questions

- Does the assistant actually retrieve memory items the way this assumes? Worth proving with three
  hand-written items before building the compiler — cheaper than discovering it after.
- Should `knowledge build` be folded into `bootstrap` so the tree is always consistent, or stay a
  separate step that must be run in the right order? Separate is clearer but makes a stale tree
  possible.
- Is `##` the right split level for GlobalMart's actual documents, or should it be configurable per
  file?
- Is there an AI Lake path for documents that this investigation missed? The ai-lake service exists
  in gdc-nas but showed no knowledge-document endpoint; a short spike would close the question
  properly rather than concluding from absence of evidence.
- Should `strategy` default to `AUTO` (retrieved on relevance) or `ALWAYS` (injected into every
  prompt) per document? `AUTO` is the safer default for volume; a short glossary might justify
  `ALWAYS`. Expose it as front matter and pick `AUTO` as the default.
- Agents are org-scoped and therefore absent from a published workspace. Does GlobalMart need an
  agent personality to be useful in a fresh org, and if so does that become a sibling feature
  capturing the org layout?

## Outcome (2026-09-20)

Built, published, and verified in the live org. 448 tests, ruff and mypy clean.

```
docs/knowledge/metric-hierarchy.md  ->  14 memory items

GET /api/v1/entities/workspaces/globalmart/memoryItems   14 items
second publish                                           changed: False
each of the 12 domain children                           14 items
domains validate --strict                                clean
```

GlobalMart's AI channels had been empty since the project started. This is the first content
in them, which also means FEAT-004's per-domain AI filtering has finally filtered something
real rather than a fixture.

### The design changed, because the platform said so

**`instruction` is capped at 255 characters.** Discovered by being rejected by the API on
the first build. The spec's plan — one memory item per `##` section — is not merely
awkward at that size, it is not expressible: a section that fits in 255 characters is a
paragraph with extra steps.

So the unit of compilation is a **paragraph**. Write one idea per paragraph; each becomes a
retrievable item. A paragraph over the cap fails the build naming the file, the heading and
its opening words. `description` (10000 chars) carries provenance instead, so an item read
in the org can be traced back to the Markdown that produced it.

This also answers the spec's open question about `##` being the right granularity: it was
never available. The remaining question — whether *paragraph* granularity retrieves well —
is task 20 and still needs a human to ask the assistant something only the document answers.

### A real bug in shipped code, found by publishing

The second publish reported `changed: True` and would have done so forever. The server
stores `keywords` as a **set** and returns its own order, unrelated to what was sent — so
`model_digest` saw a difference on every run. This is precisely the failure the audit fields
caused during FEAT-002, in a different field, and it was invisible until the first object
with a keyword list was published. `compare.UNORDERED_FIELDS` now normalises it, with a
regression test and a guard that a genuine keyword edit is still a difference.

### Two decisions worth naming

1. **Ownership is marked, not positional.** Every compiled item carries the reserved tag
   `knowledge`, and a build reconciles only against items carrying it. "This build owns
   everything in `memory_items/`" would have deleted captured or hand-authored items the
   first time it ran — the channel is shared. `test_a_build_never_touches_an_item_it_does_not_own`
   is the test that matters in this feature.

2. **"No domains" means universal, not unclassified.** A document listing no domains is
   tagged `knowledge/shared` and reaches every child via `domains.yaml`'s `shared.ai`.
   Letting it mean "no domain" would leave the item uncovered and fail
   `domains validate --strict` — the right outcome for something nobody classified, the
   wrong one for something deliberately universal. Found because the coverage gate caught it.

### Not done

- **Task 20 — does the assistant actually retrieve these usefully?** The items are live and
  the question is now cheap to ask, but it needs a human to judge the answer. This is the
  one open acceptance question, and building more will not settle it.
- **Agent personalities remain org-scoped and absent**, as the spec's Out of Scope says.
  A published GlobalMart still arrives with no agent. Unchanged by this feature and still
  worth its own.
