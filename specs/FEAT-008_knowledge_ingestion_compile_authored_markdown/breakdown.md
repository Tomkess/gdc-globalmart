## Technical Breakdown — FEAT-008: Knowledge ingestion

> **Continuity.** No new package, no new config file, no new publish path. This adds one module
> (`knowledge.py`) and one CLI group (`knowledge build [--check]`) to `src/globalmart/`, and writes
> into the `memory_items` channel of the tree FEAT-001 already captures and FEAT-002 already
> publishes. `write_tree` gives byte stability and orphan pruning for free; `count_objects` already
> counts the channel; FEAT-004's `ai_context.filter_ai_context` already filters it by tag.

> **The one thing this feature must not get wrong.** The compiled output shares a directory with
> captured content. A build that deleted a memory item it did not create, or a capture that wiped
> every compiled item, would both be silent data loss. Ownership is therefore explicit and
> marker-based, not positional — see **The ownership marker** below.

---

### Components

| Component | What it does | New/existing | Effort |
|---|---|---|---|
| `docs/knowledge/*.md` | Authored source. Optional YAML front matter: `domains`, `keywords`, `strategy`, `split_level`. Ships with one real worked example (`net-revenue.md`), not a lorem-ipsum placeholder — the granularity question can only be judged against real content. | New | S |
| `src/globalmart/knowledge.py` | The whole compiler. `parse_document(path) -> KnowledgeDocument` (front matter + `##` sections), `compile_documents(paths) -> list[CatalogDeclarativeMemoryItem]`, `apply_to_tree(model, items)` (replace exactly the owned set), `build_knowledge(...) -> KnowledgeReport`. Pure except for reading the Markdown; the tree write goes through `layout_io.write_tree`. | New | M |
| `src/globalmart/cli.py` | `globalmart knowledge build [--source docs/knowledge] [--layout ...] [--check]`. Writes **local files only**, so per ADR 002 it takes `--check` (the CI-gate form), never `--apply`. | Modified | S |
| `.github/workflows/ci.yml` | `globalmart knowledge build --check` beside the other three gates. | Modified | S |
| `tests/fixtures/knowledge/` | Small authored documents: one well-formed, one with front matter, one with an oversized section, one with no `##` headings, one with duplicate headings. | New | S |
| `tests/test_knowledge.py` | Parser, id determinism, ownership, size guard, the capture-then-build convergence test. | New | M |
| `docs/knowledge.md` | How to author, what compiles to what, the ordering rule, and the honest statement that there is no upload API. | New | S |

---

### Data Model

**`KnowledgeSection`** (frozen): `heading: str`, `body: str`, `level: int`.

**`KnowledgeDocument`** (frozen): `path: Path`, `title: str`, `sections: tuple[KnowledgeSection, ...]`,
`domains: tuple[str, ...]`, `keywords: tuple[str, ...]`, `strategy: MemoryStrategy`,
`split_level: int`.

**`MemoryStrategy`** (`StrEnum`): `ALWAYS`, `AUTO`. Required by the API with no default; the
compiler sets it explicitly. `AUTO` is the default for volume — `ALWAYS` injects into every prompt,
which is right for a short glossary and wrong for anything longer.

**`KnowledgeReport`**: `documents: int`, `items: int`, `created/updated/removed/unchanged: list[str]`,
`changed: bool`.

**Emitted item** — the shape verified against the live org:

```yaml
id: net_revenue_what_it_excludes      # <file-stem>_<heading-slug>, deterministic
title: What it excludes               # the heading, verbatim
instruction: <section body>           # what the assistant is told
keywords: [net, revenue, excludes]    # heading terms + explicit front matter
strategy: AUTO
tags: [knowledge, domain/finance]     # `knowledge` is the ownership marker
```

#### The ownership marker

Every compiled item carries the reserved tag **`knowledge`**. A build computes the full set of
items it would emit, then reconciles **only** against existing memory items carrying that tag:
owned items are created, updated or removed; any memory item without the tag is left untouched.

Positional ownership ("everything in `memory_items/`") was rejected: the channel is shared with
whatever a capture pulls back, and hand-authored items are legitimate. A marker makes ownership a
property of the object rather than of where it happens to sit, so the rule survives a re-capture.

#### Ids

`<file-stem>_<heading-slug>`, both slugified to `[a-z0-9_]`. Deterministic, so a diff shows content
changes rather than churn, and greppable from the item back to the Markdown that produced it. A
duplicate heading within one document is a **build error**, not a silently overwritten item.

#### The ordering hazard, stated plainly

`bootstrap` (capture) and `knowledge build` both write the same tree, and `write_tree` prunes
orphans. So:

- **`bootstrap` after `knowledge build`, against an org that lacks the items, deletes them.** This
  is correct behaviour — the tree mirrors the org — but it surprises. The fix is ordering:
  `bootstrap` then `knowledge build` then publish.
- **Capture-then-build converges** once the items have been published, because the capture returns
  them and the build re-emits them identically. A test proves this rather than assuming it.

Documented in `docs/knowledge.md` and enforced by the `--check` CI gate, which fails a tree that
has drifted from the Markdown in either direction.

---

### Integration Points

- **FEAT-001** — `read_tree` / `write_tree` (byte stability, orphan pruning), `count_objects`
  already counts `memory_items`, and `tests/test_sdk_floor.py` already asserts the SDK models the
  channel. The normalizer's canonical dump applies unchanged.
- **FEAT-002** — nothing to do. Memory items publish because they are in the layout.
- **FEAT-004** — `tags` is what `ai_context` filters on, so `domains: [finance]` in front matter
  becomes `domain/finance` and the splitter selects it with no second mapping file. This finally
  gives the AI-filtering machinery real content to filter; today the channel is empty, so that path
  is exercised only by fixtures.
- **FEAT-006** — memory items are counted per workspace, so a knowledge regression shows up as a
  count mismatch against the repo.

---

### Test Strategy

Offline, against committed fixtures. No host.

- **Parser**: front matter parsed; absent front matter defaults (`strategy: AUTO`, no domains); `##`
  splitting; a document with no `##` emits one item from the document itself; body text preserved
  verbatim including lists and code blocks.
- **Ids**: deterministic across runs; slugified; a duplicate heading raises naming file and heading.
- **Ownership** (the core): a tree containing one captured memory item *without* the `knowledge` tag
  and one compiled item — a rebuild removes a compiled item whose section was deleted and leaves the
  captured one untouched. The negative form (positional ownership) would delete both.
- **Size guard**: a section over the limit fails naming file and heading; one just under passes.
- **Determinism**: two builds produce byte-identical trees; `normalize --check` stays clean.
- **Convergence**: build → write → read → build again produces no change (the capture-then-build
  cycle, without a host).
- **Hand edit**: a hand-edited item YAML is overwritten by the next build.
- **Domains**: `domains: [finance, sales]` becomes `tags: [domain/finance, domain/sales, knowledge]`,
  and FEAT-004's `filter_ai_context` selects it for those domains and not others.
- **CLI**: `--check` exits 1 on drift and writes nothing; exits 0 on a current tree.

---

### Implementation Order

1. `knowledge.py` — front-matter and section parsing, `KnowledgeDocument`, with unit tests.
2. Id generation and item emission, including the duplicate-heading and size guards.
3. `apply_to_tree` — the marker-based reconciliation, with the ownership test written first.
4. CLI `knowledge build [--check]`, the `.github` gate, `tests/test_cli.py` extension.
5. One real worked document under `docs/knowledge/`, built into the tree and committed.
6. Publish to `demo-cloud`, confirm the items arrive and a second publish reports no change.
7. `docs/knowledge.md`.

---

### Total Effort Estimate

| Area | Effort |
|---|---|
| Parser + emitter | M |
| Marker-based reconciliation | S |
| CLI + CI gate | S |
| Tests | M |
| Worked example + live publish | S |
| Docs | S |

**Overall: M, at the low end.** The compiler is small and entirely local; the two places to be
careful are ownership (get it wrong and a build eats captured content) and the capture/build
ordering, both of which are one well-chosen rule plus a test. The genuinely open question —
whether `##` is the right granularity for retrieval — cannot be answered by building more, only by
publishing a real document and asking the assistant something only it answers. That is step 6, and
it is deliberately early.
