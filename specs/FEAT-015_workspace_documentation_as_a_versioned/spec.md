---
abandoned_at: null
abandoned_reason: null
appetite: l
blocked_at: null
blocked_by: null
confidence: medium
created: '2026-09-21'
cycle: null
depends_on:
- feat-002
- feat-004
- feat-008
enables: []
goal: goal-01
id: feat-015
name: 'Workspace documentation as a versioned, publishable corpus: author the whole
  of GlobalMart as topic-grouped Markdown, compile and upsert it into the GoodData
  AI Knowledge document API, and gate it on coverage against the live layout, published-state
  reconciliation and answer-level retrieval'
sources: []
status: in-progress
tags: []
updated: '2026-09-21'
---

## Summary

GlobalMart's semantic layer names objects; nothing explains them. `docs/knowledge/` already
compiles short Markdown paragraphs into AI **memory items** (FEAT-008) — directives, capped at
255 characters, for standing guidance. There is no channel for the other kind of knowledge:
long-form documentation that explains the data model, what each dashboard shows, how the
warehouse refreshes, and how the twelve domains relate — the material a new analyst or a
customer's own team needs to trust and extend the workspace. GoodData Cloud added exactly that
channel in 2026: an **AI Knowledge document API** (`/api/v1/ai/{organization|workspaces/{id}}/knowledge/documents`)
that accepts whole Markdown files, chunks them server-side, and serves them through a dedicated
AI Assistant search skill. `docs/knowledge.md` (written under FEAT-008) concluded no such API
existed — checked 2026-09-18, before it shipped. That conclusion is now wrong and this feature
supersedes it for long-form content, while FEAT-008's memory-item compiler continues to own
short directives; the two channels are siblings, not competitors.

This feature authors GlobalMart's complete documentation as a topic-grouped Markdown corpus in
the repo, compiles and upserts it into that API, and — because "how to keep, maintain, validate
and preserve documentation consistent across teams" is the actual deliverable, not a byproduct —
gates it in CI on three independent checks: does every object in the parent workspace have
documentation or an explicit exclusion, does the published corpus in the org actually match the
repo, and does the AI Assistant's retrieval over it actually answer questions only the docs
answer. The result is a reference implementation of documentation as a validated artifact
instead of a wiki page that quietly stops being true.

## Appetite

`l` — 2–6 weeks

## Acceptance Criteria

- [ ] Given the parent GlobalMart workspace's full inventory (datasets, metrics, visualizations,
      dashboards, filter contexts, the data-refresh pipeline, the domain split), when the corpus
      is authored, then every one of those object classes has at least one Diátaxis-typed
      Markdown document under it, topic-grouped by directory, with front matter naming its kind,
      scope and owner.
- [ ] Given the authored corpus, when `globalmart knowledge-docs build` runs, then it validates
      front matter completeness, one Diátaxis kind per document, and per-document size against
      the retrieval-quality guidance (research notes: header-based sections, no section growing
      past self-contained), failing loudly and naming the file and violation.
- [ ] Given a validated corpus and a target profile, when
      `globalmart knowledge-docs publish --target <profile> --apply` runs, then every document is
      upserted (`PUT .../workspaces/{parent_workspace_id}/knowledge/documents`) tagged with a
      fixed ownership scope, and a second run with no repo changes reports zero changes
      (idempotent, mirroring FEAT-002's compare.py precedent).
- [ ] Given the published corpus, when
      `globalmart knowledge-docs verify --target <profile>` runs, then it reconciles repo against
      org by filename within the ownership scope: docs in the repo but not the org are reported
      missing, docs in the org carrying the ownership scope but absent from the repo are reported
      orphaned and prunable, and any document without the ownership scope is left untouched and
      unreported as ours.
- [ ] Given the parent workspace's live inventory, when `globalmart knowledge-docs coverage` runs,
      then every metric, dataset, visualization and dashboard is confirmed referenced by at least
      one corpus document or explicitly excluded with a written reason in the manifest, exit
      non-zero otherwise — same shape as FEAT-003's `check_coverage`.
- [ ] Given the published corpus and a fixed set of questions each answerable only from one
      document, when the answer-level validation suite runs against the AI Assistant, then each
      answer is asserted (fact-containment, not exact match) to surface the expected document,
      and a real retrieval regression fails the suite rather than passing silently.
- [ ] Given a cold rebuild into a fresh org (goal-01's acceptance bar), when
      `globalmart rebuild --target <profile> --apply` completes, then the knowledge-docs publish
      step either runs as part of it or the rebuild report explicitly names it as a required
      separate step and why — the gap is stated, not silently left open.

## Scope

- A topic-grouped Markdown corpus under a new `docs/knowledge-corpus/` tree (name pending
  CONTRACT.md assignment at `/breakdown`), organized by Diátaxis kind and by subject: data model
  and LDM, metric definitions and hierarchy, each domain's dashboards and visualizations, the
  data-refresh/warehouse pipeline (FEAT-005's custody model), the domain split (FEAT-004's
  pull-in rule), and how AI context (memory items, this corpus, agents) fits together.
- A compiler/validator (`globalmart knowledge-docs build`) enforcing front-matter schema,
  Diátaxis-kind-per-document, and section-size guidance.
- A publisher (`globalmart knowledge-docs publish --target <profile> [--apply]`) upserting the
  corpus to the parent workspace via the AI Knowledge document API, following STEERING's
  `--apply` convention.
- A reconciler/verifier (`globalmart knowledge-docs verify`) comparing repo state to org state
  by filename within an ownership scope, never touching documents outside it.
- A coverage gate (`globalmart knowledge-docs coverage [--strict]`) checked against the parent
  layout, reusing `coverage.py`'s pattern of an explicit-exclusion allowlist.
- An answer-level validation harness: a small fixed question set with expected-fact assertions,
  runnable in CI against a published target.
- Reactivating the dormant `knowledge_ids` field already present on `AiSelection`
  (`domains.py`) and the `("knowledge", ("ai_knowledge", "knowledge", "knowledge_items"), ...)`
  channel stub already in `ai_context.py` — both written by FEAT-008/FEAT-004 for a document
  concept the SDK didn't model yet, and unused since. This feature is what arrives to fill them;
  the exact reconciliation (per-domain `scopes` selection vs. the existing tag-based selection)
  is an open question below, not pre-decided here.

## Out of Scope

- Changing FEAT-008's memory-item compiler or its 255-character directive model. The two
  channels stay separate per the summary's table.
- Org-level knowledge documents (`/api/v1/ai/organization/knowledge`). This feature publishes at
  the parent-workspace level only, relying on documented child-inheritance; org-level reaches
  workspaces outside GlobalMart and is a different blast radius.
- Automated authoring or LLM-generated document content. The corpus is hand-written; only
  compilation, publishing and validation are automated.
- A staleness/age-based gate (e.g. "flag docs untouched for 180 days"). Deliberately dropped in
  favor of coverage-against-live-layout, which catches the same drift without a false-positive
  clock (decision recorded during idea capture, 2026-09-21).
- Non-Markdown formats. The API accepts TXT and Markdown; this feature authors Markdown only.

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| API is flagged **Experimental** (shipped 2026-03-26) — surface or chunking behavior may change | medium | high | Isolate all API calls behind `knowledge_docs.py`; no other module touches the endpoint directly; pin and note the API version consulted |
| Server-side chunking is opaque — only `numChunks` is observable, not chunk boundaries | medium | medium | Treat chunking as advisory (log `numChunks` deltas); do not build correctness assertions on chunk count, only on retrieval outcomes |
| No native tag field on documents — only `scopes` and `title`/filename — so "ownership" must be a convention, not an API guarantee | medium | medium | Fix one reserved scope value as the ownership marker (mirrors FEAT-008's `OWNER_TAG` pattern) and reconcile within it only |
| Answer-level validation is inherently non-deterministic (LLM-in-the-loop) | high | medium | Assert fact-containment against a small fixed question set, not exact-match; allow bounded retries before failing CI |
| Corpus lives outside the SDK layout tree, so `rebuild`/`publish parent` do not carry it automatically — a real gap against goal-01's "no manual step" | high | medium | Add an explicit `knowledge-docs publish` step to `rebuild.py`'s `RebuildStep` chain, or document the gap loudly in the rebuild report rather than silently omitting it |
| 255-char memory items (FEAT-008) and long-form documents (this feature) both claim to be "the workspace's knowledge" — risk of authors duplicating content in both | low | medium | State the split explicitly in both features' docs; corpus coverage gate references FEAT-008 items by id where a memory item already covers a fact, rather than re-authoring it |

## Dependencies

- **Depends on:** feat-002 (`TargetProfile`, `--target`/`--apply` publish convention),
  feat-004 (`coverage.py` pattern reused for the coverage gate; `AiSelection.knowledge_ids` and
  the `ai_context.py` knowledge channel stub this feature activates), feat-008 (sibling AI
  context channel; `docs/knowledge/` authoring precedent; the superseded "no document API"
  finding this feature corrects)
- **Enables:** none currently

## Related Research

See `summaries/research-notes.md` for full detail and sources. Key points:

- AI Knowledge document API verified live: `POST`/`PUT .../documents`, upsert-by-filename,
  `GET` list (cursor-paginated, inherits from parent + org), `GET`/`PATCH`/`DELETE` by id,
  raw-file download. TXT/Markdown only. Response includes `numChunks`.
- Writes do not propagate to children; reads inherit at query time — the opposite propagation
  model from FEAT-008's memory items, which the splitter copies per domain.
- Diátaxis (tutorial/how-to/reference/explanation) gives "grouped by topic" a defensible rule
  instead of taste, and maps naturally onto `scopes`.
- Chunking-configuration research (Vectara/NAACL 2025) found chunk config influences retrieval
  quality as much as embedding model choice; since chunking here is server-side, the applicable
  lever is authoring discipline — header-based sections, one idea per section, documents that
  don't outgrow self-contained sections.
- Docs-as-code tooling (pageworks, flue-doc-agent) treats staleness as a CI concern via a
  freshness horizon; this feature substitutes coverage-against-live-layout, judged stronger
  because it is tied to actual drift rather than elapsed time.
- Open Semantic Interchange initiative names the industry failure mode this feature demonstrates
  a fix for: the same metric logic re-defined and re-maintained separately across BI, analytics
  engineering and AI copilots.

## Open Questions

- Should the dormant `knowledge_ids` / `ai_context.py` knowledge-channel stub be repurposed to
  drive per-domain `scopes` at publish time, or does this feature define its own selection
  mechanism and leave that stub for a future in-layout knowledge concept? Affects whether
  `domains.py` (FEAT-003/004-owned) needs a change in this feature's commit per CONTRACT's rule.
- Exact module name and CLI subcommand group (`knowledge-docs` used here as a placeholder to
  avoid colliding with FEAT-008's `knowledge.py`/`globalmart knowledge` surface) — to be pinned
  in CONTRACT.md at `/breakdown`.
- Does the parent-workspace-level publish reach `demo-cloud`'s existing 12 domain children via
  inheritance cleanly, or does GoodData's inheritance model have exceptions worth verifying live
  before committing to "publish once, inherit everywhere" as the design?
- What counts as the fixed question set for answer-level validation, and does it need updating
  every time the corpus changes (coupling risk), or can it target stable, load-bearing facts only?
- Should `rebuild.py` treat a missing knowledge-docs publish as a hard failure or a warned gap,
  given goal-01's "no manual step" bar was defined before this content existed?
