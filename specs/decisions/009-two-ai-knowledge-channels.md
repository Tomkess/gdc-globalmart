# 009 — Two AI knowledge channels, and the corpus lives outside the layout

**Status:** Accepted
**Date:** 2026-09-21
**Context:** goal-01; FEAT-015. **Supersedes a finding in FEAT-008**, not the feature itself.

## Decision

GlobalMart carries **two** AI knowledge channels, and they are not alternatives:

| | AI memory items (FEAT-008, `knowledge.py`) | AI Knowledge documents (FEAT-015, `knowledge_docs.py`) |
|---|---|---|
| Unit | one paragraph, ≤ 255 characters | a whole Markdown document |
| Purpose | a standing directive the assistant should obey | documentation a person or agent looks up |
| Source | `docs/knowledge/*.md` | `docs/knowledge-corpus/<kind>/*.md` |
| Transport | inside the layout tree; `publish parent` carries it | its own REST call to `/api/v1/ai/.../knowledge/documents` |
| Reaches children | copied per-domain by the splitter, selected by tag | written to each workspace directly, one upsert each |
| Grouping | `domain/<key>` and `knowledge/shared` tags | `scopes` |
| Ownership marker | the reserved tag `knowledge` | the filename prefix `gm-corpus__` **and** the scope `globalmart-corpus` |

A fact belongs to exactly one channel. Restating a memory item inside a corpus document is
the duplication this split exists to prevent.

## The superseded finding

`knowledge.py` and `docs/knowledge.md` both stated, under "There is no document-upload API":

> Checked against the GoodData API client and gdc-nas on 2026-09-18: no knowledge-document
> model, no file ingestion.

That conclusion was drawn from the Python SDK's surface, and the Python SDK still models no
knowledge document. The API exists anyway — it shipped on **2026-03-26** (experimental) and
is reachable over REST, with a generated client in `@gooddata/api-client-tiger`'s
`KnowledgeAi` and a dedicated AI Assistant knowledge skill on top. Re-verified 2026-09-21:

    PUT    /api/v1/ai/workspaces/{ws}/knowledge/documents               upsert by filename
    GET    /api/v1/ai/workspaces/{ws}/knowledge/documents               list, cursor-paginated
    GET    /api/v1/ai/workspaces/{ws}/knowledge/documents/{id}/download the raw file
    DELETE /api/v1/ai/workspaces/{ws}/knowledge/documents/{id}          document and its chunks
    GET    /api/v1/ai/workspaces/{ws}/knowledge/search                  semantic search over chunks

FEAT-008's *design* survives intact: a 255-character cap really does make a paragraph the
only expressible unit on that channel. What does not survive is the conclusion that
compiling to memory items was the only way to get a document into a workspace. The lesson
worth keeping is narrower than it looked: **the Python SDK's coverage is not the platform's
capability**, and a "no such API" finding needs the REST surface checked too.

## Why the corpus is not in the layout tree

It cannot be. The declarative workspace model has no knowledge-document channel — `ai_context.py`
already says so, and its `("knowledge", ("ai_knowledge", "knowledge", "knowledge_items"), …)`
entry has always found nothing. Documents are written by their own endpoint and are not part
of `get_declarative_workspace`.

### Inheritance does not apply here — probed, 2026-09-21

The API inherits documents down the workspace hierarchy: a search from a workspace reaches
its ancestors and the organization, and more local knowledge outranks inherited knowledge.
This design initially relied on that, publishing once to `globalmart` and expecting the
twelve domain workspaces to see it.

They do not. Published to the parent on demo-cloud, a listing from `globalmart-finance`,
`globalmart-risk` and `globalmart-ecommerce` returned **zero** documents, and
`catalog_workspace.list_workspaces()` shows why: all thirteen workspaces report
`parent=None`. GlobalMart has no GoodData workspace hierarchy at all. "Parent" and "child"
here name a *derivation* relationship owned by this repository — the splitter emits twelve
independent workspaces (ADR 001) — and that independence is the property which makes a
domain workspace publishable into any org on its own. Inheritance was never going to reach
them.

So the corpus is written to **all thirteen workspaces**, one upsert each, and
`--parent-only` narrows it. The `publish-knowledge-docs` rebuild step does the same. The
cost is thirteen times the API calls and no other complexity: `publish_corpus` was already
parameterised by workspace, so this was a default change rather than a redesign.

The wider lesson matches the one at the top of this ADR. A documented platform behaviour was
read correctly and applied to an architecture it did not fit, and only a ten-minute
read-only probe against a real org distinguished the two. The probe was in the plan for that
reason and it earned its place.

Three further consequences, all accepted deliberately:

1. **`publish parent` does not carry the corpus.** So `rebuild.py` gains a real
   `publish-knowledge-docs` step, which fails the chain when a corpus exists and the publish
   fails, and reports a *named* `SKIPPED` when there is no corpus directory or
   `--skip-knowledge-docs` was passed. goal-01's "no manual step" bar is met literally, and
   the one softening is visible in the report rather than absent from it.
2. **A cross-org publish is a second call, not a second copy.** Portability is unaffected:
   the documents contain no org id, no user reference and no datasource — they are prose.
3. **`AiSelection.knowledge_ids` stays dormant.** It models an in-layout object the splitter
   copies and `check_coverage` demands membership for. Wiring it here would make
   `domains validate` demand coverage of objects that are not in the layout at all. Per-domain
   grouping is expressed as `scopes` derived from front-matter `domains:` instead. The field
   remains reserved for a future in-layout knowledge object, should the SDK ever model one.

## Why ownership is a filename prefix *and* a scope

The channel is shared: AI Knowledge has a UI, and a colleague uploading a PDF through it is
legitimate content that a reconcile must never delete. FEAT-008 solved the same problem with
a reserved tag and the rule "own the objects, not the directory". Documents have no tag
field — only `scopes`, `title` and `filename` — so ownership is marked twice and recognised
by **either**:

- `filename` starts with `gm-corpus__` — the reliable one, because filename is this API's
  identity and a listing always returns it;
- `scopes` contains `globalmart-corpus`.

An OR rather than an AND: were it an AND, one missing field in a listing would make our own
corpus look foreign and the next publish would propose recreating all of it. A document with
neither marker is reported as `foreign_left_alone` and is never written, never deleted, and
never counted as ours.

Pruning additionally requires **locality**. A workspace listing includes documents inherited
from parents and from the organization, and those are read-only from below, so a prune
candidate must be ours *and* live at the workspace being written.

## Why retrieval is asserted against search, not against the assistant

FEAT-008 left "does the assistant actually retrieve this well?" open, and the honest reason
was that asserting on generated prose is a flaky test. `GET /knowledge/search` removes the
problem: it runs the same semantic search over the same chunks the assistant's knowledge
skill uses, and returns the chunks, their filenames and their scores. So `retrieval.py`
asserts two things per question — the expected document is within `limit`, and the expected
facts appear in *its* chunks — with no model in the loop, nothing to retry, and a failure
that names the chunk rather than an opinion about a paragraph.

Whether the assistant *words* the answer well remains a human judgement, and is recorded as
such rather than gated.

## Alternatives rejected

**Publish at organization level** (`/api/v1/ai/organization/knowledge`). This is the one
alternative the inheritance finding makes genuinely attractive: org-level documents *are*
visible from every workspace regardless of hierarchy, so it would replace thirteen upserts
with one. It is still rejected, because it reaches every workspace in the organization
including those that have nothing to do with GlobalMart — the demo org hosts other content,
and documentation asserting that "net revenue excludes intra-company transfers" is wrong
everywhere else. Thirteen writes with a bounded blast radius beats one write with an
unbounded one. Worth revisiting for an org dedicated solely to GlobalMart.

**Compile the corpus into memory items too.** Rejected: a 24,000-character document becomes
roughly a hundred 255-character directives, each retrieved without its neighbours. That is
how a document is destroyed by being ingested.

**A staleness horizon** ("flag documents untouched for 180 days"), which is what the
docs-as-code tooling generation does. Rejected in favour of coverage against the live layout:
the subject of this documentation is machine-readable, so drift can be *detected* rather than
estimated from a clock. A date-based gate fires on documents that are still correct and stays
silent on the one whose metric was renamed yesterday.
