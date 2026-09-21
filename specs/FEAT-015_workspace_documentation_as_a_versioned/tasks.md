## Tasks — FEAT-015: Workspace documentation as a versioned, publishable corpus

> Appetite: `l`  ·  Generated: 2026-09-21  ·  Machinery and corpus built 2026-09-21
>
> **All 36 done.** The live publish, the inheritance probe, the retrieval run and the
> cold-rebuild rehearsal all ran against demo-cloud on 2026-09-21. The probe disproved
> the inheritance assumption and changed the publish default — see the Outcome section
> of spec.md and ADR 009.

- [x] 1. Update `specs/CONTRACT.md`: add `corpus.py`, `corpus_coverage.py`, `knowledge_docs.py`,
       `retrieval.py` to the module-ownership table as FEAT-015; add the five `knowledge-docs`
       CLI rows; add the three new on-disk paths plus `tests/fixtures/corpus/`; add the footnote
       that `AiSelection.knowledge_ids` and `ai_context.AI_CHANNELS`'s `knowledge` stub stay
       dormant and why.
       Pre: none
       AC: prerequisite for all — CONTRACT changes land first, per its own rule
- [x] 2. Implement `corpus.py`: `DiataxisKind`, `CorpusSection`, `CorpusDocument`,
       `CoversSelection` dataclasses, module constants (`DEFAULT_CORPUS_DIR`,
       `FILENAME_PREFIX`, `MAX_SECTION_CHARS`, `MAX_DOCUMENT_CHARS`, `MIN_SECTION_CHARS`), and
       strict front-matter parsing (unknown key raises, FEAT-008's `_parse_front_matter`
       pattern).
       Pre: task 1 complete
       AC: #1, #2
- [x] 3. Implement `corpus.py`: header-based section splitting (guard `##` inside fenced code
       blocks, per `knowledge.py`'s `in_fence` precedent), size validation against
       `MAX_SECTION_CHARS`/`MAX_DOCUMENT_CHARS`/`MIN_SECTION_CHARS`, `published_filename`
       derivation, sha256 `digest`, and `CorpusBuildReport`.
       Pre: task 2 complete
       AC: #2
- [x] 4. Write tests for `corpus.py` covering: missing/unknown front-matter keys, invalid `kind`,
       two top-level headings in one document, `##` inside a fenced code block not counted as a
       boundary, section/document size ceilings and floors, `published_filename` determinism and
       collision detection, digest stability across reparses and sensitivity to a one-character
       change. Create `tests/fixtures/corpus/` alongside.
       Pre: task 3 complete
       AC: #2
- [x] 5. Implement the `config/corpus.yaml` strict loader in `corpus_coverage.py`:
       `CorpusExclusion`, `CorpusManifest`, `load_corpus_manifest`, importing
       `PLACEHOLDER_REASONS` from `domains.py` rather than re-declaring it.
       Pre: task 1 complete
       AC: #5
- [x] 6. Write tests for the `corpus.yaml` loader: unknown key raises, an exclusion without a
       reason raises, a placeholder reason is detected.
       Pre: task 5 complete
       AC: #5
- [x] 7. Author the seed corpus — 4 documents, one per Diátaxis kind:
       `docs/knowledge-corpus/reference/data-model-overview.md`,
       `docs/knowledge-corpus/explanation/revenue-definitions.md`,
       `docs/knowledge-corpus/how_to/refresh-the-warehouse.md`,
       `docs/knowledge-corpus/tutorial/from-empty-org-to-globalmart.md`.
       Pre: task 3 complete
       AC: #1
- [x] 8. Validate the seed corpus against `corpus.py`'s parser/validator (direct function call,
       CLI not wired yet) and fix every violation until it parses clean.
       Pre: task 7 complete
       AC: #2
- [x] 9. Implement `corpus_coverage.py`: `ClassCoverage`, `CorpusCoverageReport`,
       `check_corpus_coverage(model, documents, manifest)`, `raise_for_corpus_report`, in
       report-only mode — mirrors `coverage.py`'s documented/excluded/uncovered classification.
       Pre: task 3, task 5 complete
       AC: #5
- [x] 10. Write tests for `corpus_coverage.py`: an uncovered metric with no `covers:` and no
        exclusion is fatal; a `TODO:`-style placeholder reason passes plain but fails
        `--strict`; a `covers:` pattern matching nothing is `unknown_covers` and fatal; an
        exclusion pattern matching nothing is `unmatched_exclusions` and fatal; one object
        documented by two files is fine; a regression pin against the real parent tree.
        Pre: task 9 complete
        AC: #5
- [x] 11. Run `corpus_coverage.py` report-only against the real parent tree and the seed corpus;
        record the uncovered-object counts per class to size the full-authoring tasks (12–18).
        Pre: task 9, task 10 complete
        AC: #5
- [x] 12. Implement `knowledge_docs.py`: `RemoteDocument` (with `is_ours()`),
        `PublishDocResult`, `KnowledgeDocsReport` dataclasses; `OWNER_SCOPE`; the thin API
        client (upsert, cursor-paginated list, get, delete, download) as the sole module
        touching `/api/v1/ai/workspaces/{id}/knowledge/documents`.
        Pre: task 3 complete
        AC: #3, #4
- [x] 13. Implement `knowledge_docs.py`: `publish_corpus` (digest-based idempotent upsert,
        `--apply` gate, ADR-002-style rehearsal-by-default) and `verify_corpus`
        (`missing_in_org` / `orphaned_in_org` / `foreign_left_alone` reconciliation via
        `is_ours()`'s OR logic).
        Pre: task 12 complete
        AC: #3, #4
- [x] 14. Write tests for `knowledge_docs.py` against a `FakeKnowledgeApi`: no writes without
        `--apply`; second publish with an unchanged repo reports `changed is False` and every
        result `unchanged`; a foreign document (no prefix, no `OWNER_SCOPE`) is
        `foreign_left_alone` and appears in no other bucket; listings with `scopes` present on
        some rows and absent on others still classify correctly; two-page cursor pagination is
        fully consumed; `numChunks` deltas are logged and asserted on by nothing; `verify
        --prune --apply` deletes exactly the orphans.
        Pre: task 13 complete
        AC: #3, #4
- [x] 15. Wire `globalmart knowledge-docs build | publish | verify | coverage` into `cli.py`
        (registration only, no logic): `--apply` on `publish` and `verify --prune`, `--strict`
        on `coverage`.
        Pre: task 3, task 9, task 13 complete
        AC: #2, #3, #4, #5
- [x] 16. Run the first live publish of the seed corpus (`knowledge-docs publish --target
        demo-cloud --apply`), then list a domain child workspace's documents to probe whether
        parent-level inheritance reaches it.
        Pre: task 15 complete
        AC: #3
- [x] 17. Record the inheritance-probe result (in `breakdown.md` or a note). If inheritance has
        exceptions, add a `--per-child` fallback flag to `publish_corpus` looping the same
        upsert over `manifest.keys()`.
        Pre: task 16 complete
        AC: #3
- [x] 18. Author the `metrics` scope documents (L1–L5 hierarchy, naming conventions, why 747
        metrics carry no visualization) until `corpus_coverage` reports zero uncovered metrics
        or a written exclusion for each.
        Pre: task 11 complete
        AC: #1, #5
- [x] 19. Author the `data-model` scope documents (the LDM by subject area, join graph, the two
        date instances, why pruning is dataset-level) until zero uncovered datasets.
        Pre: task 11 complete
        AC: #1, #5
- [x] 20. Author the `dashboards/<domain>` scope documents, one per domain (12), until zero
        uncovered dashboards and visualizations.
        Pre: task 11 complete
        AC: #1, #5
- [x] 21. Author the `domains` scope documents (FEAT-004's split: the pull-in rule,
        parent-as-editing-surface, what a child does and does not carry).
        Pre: task 11 complete
        AC: #1
- [x] 22. Author the `warehouse` scope documents (FEAT-005's custody model, the refresh story,
        `data verify` / `data load`).
        Pre: task 11 complete
        AC: #1
- [x] 23. Author the `ai-context` scope documents (how memory items, this corpus, parameters and
        agents fit together; when to author which).
        Pre: task 11 complete
        AC: #1
- [x] 24. Author the `getting-started` tutorial document (fresh org to a working GlobalMart).
        Pre: task 11 complete
        AC: #1
- [x] 25. Run `corpus_coverage.py` against the full authored corpus and the real parent tree;
        fill `config/corpus.yaml` exclusions with real reasons until the report is clean.
        Pre: tasks 18–24 complete
        AC: #5
- [x] 26. Promote `corpus_coverage` from report-only to fatal; add `knowledge-docs build` and
        `knowledge-docs coverage --strict` as offline pre-merge CI gates.
        Pre: task 25 complete
        AC: #5
- [x] 27. Author `config/corpus-questions.yaml` — 8 to 12 questions, each citing a document with
        `anchor: true` and one or more `expect_facts` strings.
        Pre: task 25 complete
        AC: #6
- [x] 28. Implement `retrieval.py`: `RetrievalQuestion`, `RetrievalOutcome`, `RetrievalReport`
        dataclasses; casefolded, whitespace-collapsed fact-containment matching; a bounded-retry
        (`--attempts`, default 3) harness built on `gd_agents.a2a.client.A2ALane`.
        Pre: task 27 complete
        AC: #6
- [x] 29. Wire the offline coupling guard into `knowledge-docs build`: every `expect_facts`
        string must appear verbatim in its named, anchored document, failing at build time
        with the question id if it doesn't.
        Pre: task 28 complete
        AC: #6
- [x] 30. Write tests for `retrieval.py` against a stubbed `A2ALane`: fact-containment is
        casefold/whitespace-insensitive and rejects paraphrase; three failing attempts fail the
        suite, a pass on attempt three passes it; a question naming a non-`anchor` document
        fails at load time, not at ask time.
        Pre: task 28, task 29 complete
        AC: #6
- [x] 31. Wire `globalmart knowledge-docs retrieval` into `cli.py` and run it live against
        `demo-cloud` until the full question set passes.
        Pre: task 30 complete, task 16 (or 17) complete
        AC: #6
- [x] 32. Add the `publish-knowledge-docs` step to `rebuild.py`'s `RebuildStep` chain
        (immediately after `publish-parent`), `RebuildOptions.skip_knowledge_docs`, and
        `_run_publish_knowledge_docs`; a missing `docs/knowledge-corpus/` directory or
        `--skip-knowledge-docs` yields `StepStatus.SKIPPED` with a named reason, never a
        silent omission.
        Pre: task 13 complete
        AC: #7
- [x] 33. Write tests for the `rebuild.py` step: it is planned in the chain; a missing corpus
        produces a named skip; a publish failure raises `RebuildAbortedError` like every other
        step.
        Pre: task 32 complete
        AC: #7
- [x] 34. Run a cold-rebuild rehearsal (`globalmart rebuild --target <fresh-target> --apply`)
        and confirm `publish-knowledge-docs` appears among the planned/executed steps in the
        report.
        Pre: task 32 complete
        AC: #7
- [x] 35. Correct `knowledge.py`'s docstring — the "There is no document-upload API" paragraph
        is now false — to point at FEAT-015 and state the two-channel split; write
        `specs/decisions/008-*.md` recording that the 2026-09-18 finding is superseded, why the
        corpus lives outside the layout tree, and why ownership is filename-prefix-plus-scope.
        Pre: task 13 complete
        AC: none directly — corrects the Summary's superseded-finding claim
- [x] 36. [DECISION NEEDED: does the pre-merge CI gate get org credentials, and may an
        LLM-in-the-loop job block a merge?] Wire CI: `knowledge-docs build` and `knowledge-docs
        coverage --strict` as pre-merge gates (already added in task 26); add
        `knowledge-docs retrieval --target demo-cloud` as a separate credentialed job, post-merge
        or on-demand unless this decision reverses that split — reversing it needs a
        `GLOBALMART_TOKEN__*` secret in the PR workflow and an accepted flake budget.
        Pre: task 26, task 31 complete
        AC: #2, #5, #6
