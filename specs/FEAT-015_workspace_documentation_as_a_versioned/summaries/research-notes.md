# FEAT-015 research notes

Gathered 2026-09-21. Two questions: what does the GoodData AI Knowledge channel actually
accept, and how do teams keep documentation of this kind from rotting.

## 1. The platform capability, verified

GoodData Cloud shipped an AI Knowledge **document** API; the UI landed 2026-03-26 as an
experimental feature, the API predates it.

Base paths:

- organization: `/api/v1/ai/organization/knowledge`
- workspace: `/api/v1/ai/workspaces/{workspace_id}/knowledge`

Operations on `/documents`:

| Operation | Method | Notes |
|---|---|---|
| Create | `POST` | `multipart/form-data`; `409 Conflict` if the filename already exists |
| **Upsert** | `PUT` | creates or replaces by filename — the idempotent publish primitive |
| List | `GET` | visible = local + inherited from parents + org-level; cursor paginated |
| Get metadata | `GET /{id}` | |
| Patch metadata | `PATCH /{id}` | metadata only, no re-ingestion |
| Delete | `DELETE /{id}` | removes the document *and its chunks* |
| Download raw file | `GET` download | inherited and org-level docs are readable |

Form fields: `file` (required), `title`, `scopes` (repeatable / CSV). Accepted content per
the UI announcement: **TXT and Markdown**.

Response: `id`, `filename`, `success`, `message`, **`numChunks`**.

Three consequences that shape the design:

1. **`numChunks` means the server chunks.** Chunking is not ours to configure. What we
   control is heading structure and document size — an authoring rule, not a parameter.
2. **Writes do not propagate; reads inherit.** "The write path does not copy the document
   into child workspaces. Child workspaces inherit it at query time." So a parent-level
   upsert covers all 12 domain children, and inherited documents are read-only from below.
   This is the opposite of FEAT-008's memory items, which the splitter copies into children.
3. **Filename is the identity.** Upsert-by-filename plus list plus raw download gives full
   reconciliation without keeping local state — no id ledger to drift out of sync.

A document can be **disabled** (excluded from search, not deleted). A dedicated AI Assistant
knowledge skill searches the corpus using the query and conversation context. The release
also added persistent document storage so the retrieval index can be rebuilt.

### This supersedes a FEAT-008 finding

`docs/knowledge.md` states, under "There is no document-upload API": *"Checked against the
GoodData API client and gdc-nas on 2026-09-18: no knowledge-document model, no file
ingestion."* That was either wrong at the time or true only of the client surface consulted.
The API exists. FEAT-008's conclusion — that uploading a document must mean compiling it
into ≤255-char memory items — is no longer the only option available.

The two channels stay separate and complementary:

| | FEAT-008 AI memory items | FEAT-015 AI Knowledge documents |
|---|---|---|
| Unit | one paragraph, ≤ 255 chars | a whole Markdown document |
| Purpose | standing directive, always or on relevance | long-form documentation, retrieved on search |
| Propagation | split into each child workspace | written once, inherited at query time |
| Grouping | `domain/<key>` and `knowledge/shared` tags | `scopes` |
| Carried by | the layout tree (`publish parent`) | its own API call, outside the layout |

Sources:
- https://www.gooddata.ai/docs/cloud/ai/ai-knowledge/#working-with-documents
- https://www.gooddata.com/docs/cloud/api-and-sdk/api/api_reference_all/ (OpenAPI: Knowledge)
- https://www.gooddata.ai/docs/cloud/whats-new-cloud/ (2026-03-26 entry)
- https://github.com/gooddata/gooddata-ui-sdk/blob/master/libs/api-client-tiger/src/generated/ai-json-api/api.ts (`KnowledgeAi`)
- https://www.gooddata.ai/docs/cloud/ai/use-ai_assistant/agentic-capabilities/skills/knowledge-skill/

## 2. How the corpus should be shaped

**Diátaxis** (Procida; adopted by Canonical, Sequin and others) puts every document in
exactly one of four categories — tutorial, how-to, reference, explanation — each with its
own writing rules. It is the defensible answer to "grouped by topic": the grouping follows a
rule rather than taste, and it maps onto `scopes` directly. For a workspace corpus the useful
reading is that *reference* (what the metric is, what the dashboard shows) and *explanation*
(why net revenue excludes intra-company transfers, why the fiscal year starts in February)
must not be mixed in one document, because the first is generated from the layout and the
second can only be authored.

**Chunking research bears on authoring, not on config.** A Vectara study at NAACL 2025 tested
25 chunking configurations against 48 embedding models and found chunking configuration
influenced retrieval quality as much as the choice of embedding model. Header-based splitting
is the consensus default for Markdown and technical docs, and propagating the heading
hierarchy as chunk metadata is what enables section-filtered retrieval. Reported sweet spot
for QA over technical documentation is 200–400 tokens per chunk, with a quality cliff
observed around 2,500 tokens of context. Since GoodData chunks server-side, the lever we hold
is: one idea per section, headings that read as standalone titles, and documents that do not
grow past the point where their sections stop being self-contained.

Sources:
- https://diataxis.fr / https://github.com/evildmp/diataxis-documentation-framework
- https://ubuntu.com/blog/diataxis-a-new-foundation-for-canonical-documentation
- https://blog.sequinstream.com/we-fixed-our-documentation-with-the-diataxis-framework/
- https://www.firecrawl.dev/blog/best-chunking-strategies-rag
- https://www.premai.io/blog/rag-chunking-strategies-the-2026-benchmark-guide/

## 3. How it stays true

Documentation drift is the failure mode, and the current tooling generation treats it as a CI
concern rather than a review concern. The pattern common to `pageworks`, `flue-doc-agent` and
EkLine's docs reviewer: structured front matter, a staleness horizon (pageworks uses 180
days), and CI assertions that block broken links, schema violations and stale content before
merge.

A workspace corpus can do strictly better than a date-based horizon, because the thing being
described is itself machine-readable. Coverage can be checked against the live layout: every
metric, dataset, visualization and dashboard is either documented or explicitly excluded with
a written reason. That is the same shape as the existing `domains validate --strict` gate, so
the repo already has the precedent and the reviewer habit.

On the metric-semantics side, the **Open Semantic Interchange** initiative (launched 2025;
dbt Labs, Snowflake, Salesforce and others) is the industry framing for "consistent across
teams": define a metric once in vendor-neutral YAML and have every tool consume it. The
recurring failure it names is the one this feature demonstrates a fix for — analytics
engineering, BI and AI copilots each keeping their own copy of the same logic, so every change
costs three edits and usually gets two.

The open question FEAT-008 left unanswered — *whether the assistant actually retrieves this
well* — is answered here rather than deferred again: ask the assistant questions only the
documents answer, and assert on the answer.

Sources:
- https://github.com/alexsmedile/pageworks
- https://github.com/opsydyn/flue-doc-agent
- https://ekline.io/blog/a-technical-guide-to-the-diataxis-framework-for-modern-documentation
- https://atlan.com/know/ai-agent/semantic-layer/semantic-layer-for-analytics/
- https://omni.co/articles/best-semantic-layer-for-ai-and-bi-2026
