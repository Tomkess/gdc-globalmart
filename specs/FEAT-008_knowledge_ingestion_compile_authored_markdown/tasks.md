## Tasks — FEAT-008: Knowledge ingestion

> Appetite: `m`  ·  Generated: 2026-09-20

- [x] 1. Create `src/globalmart/knowledge.py` with `MemoryStrategy` (`StrEnum`: `ALWAYS`, `AUTO`), the frozen dataclasses `KnowledgeSection` (`heading`, `body`, `level`) and `KnowledgeDocument` (`path`, `title`, `sections`, `domains`, `keywords`, `strategy`, `split_level`), `KnowledgeReport`, and `KnowledgeError(GlobalmartError)`. Constants: `OWNER_TAG = "knowledge"`, `DOMAIN_TAG_PREFIX = "domain/"`, `MAX_SECTION_CHARS`.
       AC: #1

- [x] 2. Implement front-matter parsing: a leading `---` block parsed with `yaml.safe_load`, keys `domains`, `keywords`, `strategy`, `split_level`, rejecting any other key by name (the same strict-parsing rule `domains.py` uses — a typo must not silently mean "no domains"). Absent front matter is valid and yields the defaults.
       Pre: task 1
       AC: #3, #5

- [x] 3. Implement section splitting: the document title comes from a leading `#` heading or the file stem; sections split on `##` (or `split_level`); a document with no such heading emits one section from the whole body. Body text is preserved verbatim, including lists and fenced code blocks.
       Pre: task 2
       AC: #1, #3

- [x] 4. Implement `slugify` and deterministic id generation `<file-stem>_<heading-slug>`, both reduced to `[a-z0-9_]`. A duplicate heading within one document raises `KnowledgeError` naming the file and the heading rather than silently overwriting an item.
       Pre: task 3
       AC: #1

- [x] 5. Implement keyword derivation: terms from the heading (lowercased, stop-words dropped, deduplicated) unioned with explicit `keywords` front matter, sorted for stability. Derived keywords are a default, never the mechanism — explicit ones always survive.
       Pre: task 4
       AC: #3

- [x] 6. Implement the size guard: a section body longer than `MAX_SECTION_CHARS` raises `KnowledgeError` naming the file and heading. An item too large to retrieve usefully is a build failure, not a silent emission.
       Pre: task 3
       AC: #7

- [x] 7. Implement `compile_documents(paths) -> list[CatalogDeclarativeMemoryItem]`: one item per section carrying `id`, `title`, `instruction`, `keywords`, `strategy`, and `tags` = `[OWNER_TAG] + [domain/<d> for d in domains]`, sorted by id. A duplicate id *across* documents is also an error.
       Pre: tasks 4, 5, 6
       AC: #1, #3, #5

- [x] 8. Write `tests/fixtures/knowledge/` — `net_revenue.md` (well-formed, two sections), `with_front_matter.md` (domains + keywords + strategy), `oversized.md` (one section past the limit), `no_headings.md`, `duplicate_headings.md`.
       Pre: task 1
       AC: #1, #7

- [x] 9. Write `tests/test_knowledge.py` part 1 — parsing and emission: front matter parsed and defaulted; an unknown front-matter key raises naming it; `##` splitting; a no-heading document yields one item; body preserved verbatim; ids deterministic and slugified; duplicate headings raise; keywords derived and unioned; the size guard fires and its just-under case passes.
       Pre: tasks 7, 8
       AC: #1, #3, #7

- [x] 10. Implement `apply_to_tree(model, items) -> KnowledgeReport` — the marker-based reconciliation. Replace exactly the set of existing memory items tagged `OWNER_TAG`; create, update and remove within that set; leave every untagged memory item untouched. Report which ids were created, updated, removed and unchanged.
       Pre: task 7
       AC: #4, #8

- [x] 11. Write `tests/test_knowledge.py` part 2 — **the ownership test, the one that matters**: a tree holding one captured memory item *without* the marker tag plus two compiled items; after a rebuild in which one section was deleted, the removed compiled item is gone and the captured item is untouched. Assert the negative too: positional ownership ("everything in `memory_items/`") would have deleted both.
       Pre: task 10
       AC: #4

- [x] 12. Implement `build_knowledge(source_dir, layout_path, *, check=False) -> KnowledgeReport`: read the tree, compile, apply, and either write via `write_tree` or (under `check`) compare against a staged tree and report drift without writing.
       Pre: task 10
       AC: #2, #4

- [x] 13. Write `tests/test_knowledge.py` part 3 — determinism and convergence: two builds produce byte-identical trees; build → write → read → build again reports no change (the capture-then-build cycle without a host); a hand-edited memory item YAML is overwritten by the next build; `normalize --check` stays clean on the built tree.
       Pre: task 12
       AC: #2, #8

- [x] 14. Write `tests/test_knowledge.py` part 4 — domain tagging: `domains: [finance, sales]` produces `tags` containing `domain/finance` and `domain/sales` plus the marker, and FEAT-004's `ai_context.filter_ai_context` selects the item for those domains and not for others. This is the first real content that machinery has ever filtered.
       Pre: task 12
       AC: #5

- [x] 15. Add `globalmart knowledge build [--source docs/knowledge] [--layout ...] [--check]` to `cli.py`. Local-file writer, so `--check` (the CI-gate form) and never `--apply`. Print the report; exit 1 under `--check` when the tree would change.
       Pre: task 12
       AC: #1, #2

- [x] 16. Extend `tests/test_cli.py`: `knowledge build` writes items and exits 0; `--check` exits 1 on drift and writes nothing; `--check` exits 0 on a current tree; the command carries no `--apply`.
       Pre: task 15
       AC: #2

- [x] 17. Write `docs/knowledge/net-revenue.md` — one **real** worked document about GlobalMart's revenue definitions, not a placeholder. The granularity question can only be judged against real content, and this is what gets published in task 19.
       Pre: task 15
       AC: #1

- [x] 18. Run `globalmart knowledge build` against the committed tree, review the emitted items as a diff, confirm `normalize --check` and `knowledge build --check` both pass, and commit the tree change.
       Pre: task 17
       AC: #1, #2

- [x] 19. Publish to `demo-cloud` with FEAT-002, confirm the memory items appear in the org via `GET /api/v1/entities/workspaces/globalmart/memoryItems`, and run a second publish confirming `changed: False`.
       Pre: task 18
       AC: #6

- [ ] 20. **[JUDGEMENT — needs the user, still open]** Ask the GlobalMart assistant a question only the published document answers, and judge whether section-level chunks retrieve usefully. This is the open question the spec says cannot be answered by building more. If `##` proves wrong, `split_level` already exists to change it.
       Pre: task 19
       AC: #1

- [x] 21. Add `globalmart knowledge build --check` to `.github/workflows/ci.yml` beside the other gates, so Markdown edited without rebuilding fails the PR.
       Pre: task 18
       AC: #2

- [x] 22. Write `docs/knowledge.md`: how to author, what compiles to what, the ownership marker and why it is marker-based rather than positional, the capture-then-build ordering rule, and the plain statement that no document-upload API exists so "upload" means compile.
       Pre: task 18
       AC: #1, #4
