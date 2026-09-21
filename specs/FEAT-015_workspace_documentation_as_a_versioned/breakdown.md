## Technical Breakdown — FEAT-015: Workspace documentation as a versioned, publishable corpus

Binding decisions taken here (the spec's five Open Questions, all closed — see
§ Resolved Open Questions for the reasoning):

1. **Modules:** `corpus.py`, `corpus_coverage.py`, `knowledge_docs.py`, `retrieval.py` — four
   new modules under `src/globalmart/`, all owned by FEAT-015.
2. **CLI group:** `globalmart knowledge-docs {build,publish,verify,coverage,retrieval}`, exactly
   as the acceptance criteria spell it. FEAT-008 keeps `globalmart knowledge build`.
3. **`AiSelection.knowledge_ids` and `ai_context.AI_CHANNELS`' `knowledge` stub are deliberately
   NOT activated.** They model an in-layout, copied-per-child object; AI Knowledge documents are
   out-of-layout and inherited at read time. No change to `domains.py` or `ai_context.py`, so no
   FEAT-003/FEAT-004-owned module moves in this feature's commit.
4. **Question set:** `config/corpus-questions.yaml`, asserted offline by `build` (every expected
   fact string must exist verbatim in the named document) and online by `retrieval`.
5. **`rebuild.py`:** gains a real `publish-knowledge-docs` step — hard failure when a corpus
   exists and the publish fails, `SKIPPED` and named in the report when the corpus directory is
   absent or `--skip-knowledge-docs` is passed. Never silently omitted.

---

### Components

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|
| `docs/knowledge-corpus/` — the authored corpus | 28–36 hand-written Markdown documents, Diátaxis-typed by directory, front matter naming kind/scope/owner/`covers`. The actual deliverable; everything else is scaffolding around it | New (content) | L |
| `src/globalmart/corpus.py` | Offline compiler/validator. Discovers documents, parses front matter against a strict schema (unknown key raises, FEAT-008's `_parse_front_matter` pattern), enforces one Diátaxis kind per document, header-based section structure, per-section and per-document size ceilings, `covers:` pattern syntax, published-filename derivation, and a stable per-document sha256 digest | New | M |
| `src/globalmart/corpus_coverage.py` | The coverage gate. Takes the loaded parent model + the loaded corpus + `config/corpus.yaml`'s exclusions and classifies every dataset, metric, visualization and dashboard as documented / excluded-with-reason / uncovered. Mirrors `coverage.py`'s `check_coverage` → `CoverageReport` → `raise_for_report` shape, including `--strict` placeholder-reason rejection | New | M |
| `src/globalmart/knowledge_docs.py` | **The only module that touches `/api/v1/ai/workspaces/{id}/knowledge/documents`.** Thin client (upsert, list-with-pagination, get, delete, download) plus `publish_corpus` and `verify_corpus` over it. Owns `OWNER_SCOPE`, the `gm-corpus__` filename prefix and the idempotency comparison | New | M |
| `src/globalmart/retrieval.py` | Answer-level validation harness. Loads `config/corpus-questions.yaml`, asks each question through the existing `gd_agents.a2a.client.A2ALane`, asserts fact-containment with bounded retries, returns `RetrievalReport` | New | M |
| `config/corpus.yaml` | Corpus manifest: schema version, per-class exclusions with written reasons, retrieval-anchor list. Loaded strictly, dumped canonically — `domains.py` as the precedent | New | S |
| `config/corpus-questions.yaml` | The fixed question set: id, question text, expected published filename, expected fact strings | New | S |
| `src/globalmart/cli.py` | Registers the `knowledge-docs` group and its five actions. Registration only, no logic (CONTRACT rule) | Existing — modified | S |
| `src/globalmart/rebuild.py` | New `publish-knowledge-docs` step in `_plan` + `step_runner`, `RebuildOptions.skip_knowledge_docs`, skip reason surfaced in `RebuildReport` | Existing — modified | S |
| `src/globalmart/knowledge.py` | Docstring correction only: the "There is no document-upload API" paragraph is now false and must point at FEAT-015 plus state the two-channel split. No behaviour change | Existing — modified | S |
| `specs/CONTRACT.md` | Adds the four modules to the ownership table, the five CLI rows, the three on-disk paths, the new fixture directory, and a footnote recording that `knowledge_ids` stays dormant | Existing — modified | S |
| `specs/decisions/008-*.md` | ADR: two AI knowledge channels, why the corpus lives outside the layout tree, why ownership is a filename prefix plus a scope | New | S |
| `tests/test_corpus.py`, `test_corpus_coverage.py`, `test_knowledge_docs.py`, `test_retrieval.py` + `tests/fixtures/corpus/` | Offline suite; no live host in unit tests | New | M |
| `.github/workflows` (or the existing CI entry point) | Three gates: `knowledge-docs build`, `knowledge-docs coverage --strict`, and a separately-triggered `knowledge-docs retrieval` job against a published target | Existing — modified | S |

---

### Data Model

#### Front matter — every corpus document (strict; unknown key raises)

```yaml
---
kind: reference            # DiataxisKind: tutorial | how_to | reference | explanation
title: Net Revenue and the Metric Hierarchy
scope: metrics             # CorpusScope, free-form slug; one of the topic groups below
owner: analytics-eng       # required, non-empty; who answers a question about this file
domains: [finance, sales]  # optional; [] or absent == universal
covers:                    # optional; what layout objects this document documents
  metrics: ["m_net_revenue", "m_gross_revenue*"]
  datasets: ["fact_orders"]
  visualizations: []
  dashboards: ["dash_finance_overview"]
anchor: true               # optional, default false; may a question set cite this document?
---
```

```python
class DiataxisKind(StrEnum):           # corpus.py
    TUTORIAL    = "tutorial"
    HOW_TO      = "how_to"
    REFERENCE   = "reference"
    EXPLANATION = "explanation"

@dataclass(frozen=True)
class CorpusSection:
    heading: str
    level: int                         # 2 or 3; a level-1 heading is the document title
    body: str
    char_count: int

@dataclass(frozen=True)
class CorpusDocument:
    path: Path                         # docs/knowledge-corpus/reference/net-revenue.md
    kind: DiataxisKind
    title: str
    scope: str
    owner: str
    domains: tuple[str, ...]
    covers: CoversSelection
    anchor: bool
    sections: tuple[CorpusSection, ...]
    body: str                          # the whole file, front matter stripped
    digest: str                        # sha256 of `body`, for idempotency
    filename: str                      # published identity: gm-corpus__<kind>__<stem>.md
    scopes: tuple[str, ...]            # OWNER_SCOPE, kind, scope, domain/<key>...

@dataclass(frozen=True)
class CoversSelection:
    metrics: tuple[str, ...]           # ids or fnmatch patterns
    datasets: tuple[str, ...]
    visualizations: tuple[str, ...]
    dashboards: tuple[str, ...]

@dataclass
class CorpusBuildReport:
    documents: int
    by_kind: dict[str, int]
    by_scope: dict[str, int]
    total_chars: int
    largest: tuple[str, int]           # (filename, chars)
    violations: list[str]              # empty == valid
```

Module constants in `corpus.py`:

```python
DEFAULT_CORPUS_DIR   = Path("docs/knowledge-corpus")
DEFAULT_MANIFEST     = Path("config/corpus.yaml")
DEFAULT_QUESTIONS    = Path("config/corpus-questions.yaml")
FILENAME_PREFIX      = "gm-corpus__"     # ownership marker #1 — see knowledge_docs.py
MAX_SECTION_CHARS    = 3_000             # ≈ the 2,500-token retrieval cliff in the research notes
MAX_DOCUMENT_CHARS   = 24_000
MIN_SECTION_CHARS    = 120               # a one-line section is a heading, not a chunk
```

#### `config/corpus.yaml`

```yaml
version: 1
parent_workspace_id: globalmart
exclusions:
  metrics:
    - id: "m_tmp_*"
      reason: Scratch metrics from the 2026-06 model bootstrap; scheduled for deletion.
  datasets: []
  visualizations:
    - id: viz_hr_headcount_sparkline
      reason: Tile variant of viz_hr_headcount; documented once at the dashboard level.
  dashboards: []
```

Loader mirrors `domains.py`: `load_corpus_manifest(path) -> CorpusManifest`, unknown keys raise
`CorpusManifestError`, an exclusion without a reason raises, and a reason in
`domains.PLACEHOLDER_REASONS` is fatal under `--strict` (the constant is imported, not
re-declared).

```python
@dataclass(frozen=True)
class CorpusExclusion:
    id: str                            # id or fnmatch pattern
    reason: str
    def reason_is_placeholder(self) -> bool: ...   # same rule as domains.Exclusion

@dataclass(frozen=True)
class CorpusManifest:
    version: int
    parent_workspace_id: str
    metrics: tuple[CorpusExclusion, ...]
    datasets: tuple[CorpusExclusion, ...]
    visualizations: tuple[CorpusExclusion, ...]
    dashboards: tuple[CorpusExclusion, ...]
    path: Path | None
```

#### `corpus_coverage.py` report

```python
@dataclass(frozen=True)
class ClassCoverage:
    total: int
    documented: dict[str, tuple[str, ...]]   # object id -> documenting filenames
    excluded: dict[str, str]                 # object id -> reason
    uncovered: tuple[str, ...]

@dataclass
class CorpusCoverageReport:
    metrics: ClassCoverage
    datasets: ClassCoverage
    visualizations: ClassCoverage
    dashboards: ClassCoverage
    unknown_covers: dict[str, str]           # id/pattern in `covers:` matching nothing -> file
    unmatched_exclusions: dict[str, str]     # manifest exclusion matching nothing -> path
    placeholder_reasons: dict[str, str]
    def is_clean(self, *, strict: bool = False) -> bool: ...
    def summary_lines(self) -> list[str]: ...
    def table_lines(self) -> list[str]: ...
    def as_dict(self) -> dict[str, Any]: ...

def check_corpus_coverage(model, documents, manifest) -> CorpusCoverageReport: ...
def raise_for_corpus_report(report, *, strict: bool = False) -> None: ...   # CorpusCoverageError
```

A pattern in `covers:` that matches nothing is `unknown_covers` and fatal — the exact analogue of
`coverage.unknown_ids`, and the thing that catches "a metric was renamed, the document was not".

#### `knowledge_docs.py` — API shapes and ownership

```python
OWNER_SCOPE = "globalmart-corpus"        # ownership marker #2, mirrors knowledge.OWNER_TAG
API_BASE    = "/api/v1/ai/workspaces/{workspace_id}/knowledge/documents"

@dataclass(frozen=True)
class RemoteDocument:
    id: str
    filename: str
    title: str | None
    scopes: tuple[str, ...]
    num_chunks: int | None
    def is_ours(self) -> bool:           # prefix match OR OWNER_SCOPE present
        return self.filename.startswith(FILENAME_PREFIX) or OWNER_SCOPE in self.scopes

@dataclass
class PublishDocResult:
    filename: str
    action: Literal["created", "updated", "unchanged", "would-upsert"]
    num_chunks: int | None
    error: str | None

@dataclass
class KnowledgeDocsReport:
    target: str
    workspace_id: str
    applied: bool
    results: list[PublishDocResult]
    missing_in_org: tuple[str, ...]      # in repo, not in org
    orphaned_in_org: tuple[str, ...]     # ours in org, absent from repo -> prunable
    foreign_left_alone: tuple[str, ...]  # neither prefix nor scope -> never reported as ours
    chunk_deltas: dict[str, tuple[int | None, int | None]]
    @property
    def changed(self) -> bool: ...
    def summary_lines(self) -> list[str]: ...
```

**Ownership is doubly marked, deliberately.** The research notes confirm `scopes` on write but
nothing guarantees `scopes` comes back on `GET /documents`. So the primary marker is the
`gm-corpus__` filename prefix (always returned — filename is the identity) and `OWNER_SCOPE` is
the secondary one. `is_ours()` is an OR, so reconciliation still works if the listing omits
scopes, and a hand-uploaded document without either marker is left untouched and is never
counted as ours (`foreign_left_alone`) — the FEAT-008 lesson applied to a different channel.

**Idempotency without local state.** A republish is "unchanged" when the org's raw download of
that filename has the same sha256 as `document.digest`. That is `compare.py`'s idea — digest the
canonical form, compare, report `changed` — adapted to a channel where the server returns the
byte-identical file it was given rather than a normalized model, so no `SERVER_OWNED_FIELDS`
equivalent is needed. `numChunks` is logged as a delta and asserted on by nothing.

#### `config/corpus-questions.yaml` and `retrieval.py`

```yaml
version: 1
questions:
  - id: q_net_revenue_intracompany
    question: Does net revenue include intra-company transfers?
    expect_document: gm-corpus__explanation__revenue-definitions.md
    expect_facts:
      - "excludes intra-company transfers"
    min_facts: 1                 # optional; default = all
```

```python
@dataclass(frozen=True)
class RetrievalQuestion:
    id: str
    question: str
    expect_document: str
    expect_facts: tuple[str, ...]
    min_facts: int

@dataclass
class RetrievalOutcome:
    question_id: str
    attempts: int
    matched_facts: tuple[str, ...]
    passed: bool
    answer_excerpt: str            # first 500 chars, for the report

@dataclass
class RetrievalReport:
    target: str
    workspace_id: str
    outcomes: list[RetrievalOutcome]
    @property
    def passed(self) -> bool: ...
```

Fact matching is casefolded, whitespace-collapsed substring containment — never exact-match,
never a numeric assertion. `--attempts N` (default 3) passes a question as soon as one attempt
contains enough facts; all N failing fails the suite.

#### On-disk paths added

| Path | What | Committed? |
|---|---|---|
| `docs/knowledge-corpus/<kind>/<slug>.md` | The authored corpus, one Diátaxis kind per directory | yes |
| `config/corpus.yaml` | Corpus exclusion manifest | yes |
| `config/corpus-questions.yaml` | The fixed retrieval question set | yes |
| `tests/fixtures/corpus/` | 6-document miniature corpus + a 3-object mini manifest | yes |

Published filename is derived, never authored: `gm-corpus__<kind>__<path-stem-slug>.md`. The
directory tree is the review surface; the flat filename is the API's identity. One function
(`corpus.published_filename(path, kind)`) owns that mapping so nothing else re-derives it.

#### Corpus topic groups (the `scope:` values, and the authoring plan)

| scope | kinds | Covers |
|---|---|---|
| `data-model` | reference, explanation | The LDM: 225 datasets by subject area, the join graph, the two date instances, why pruning is dataset-level |
| `metrics` | reference, explanation | The L1–L5 metric hierarchy (1091 metrics), naming conventions, the 747 metrics on no visualization and why they exist |
| `dashboards/<domain>` | reference | One document per domain (12): what its dashboards show, which questions they answer |
| `warehouse` | how_to, explanation | FEAT-005's custody model, the 215 tables, `data verify`/`data load`, the refresh story |
| `domains` | explanation | FEAT-004's split: the pull-in rule, parent-as-editing-surface, what a child does and does not carry |
| `ai-context` | explanation, how_to | How memory items (FEAT-008), this corpus, parameters and agents fit together; when to author which |
| `getting-started` | tutorial | One tutorial: from a fresh org to a working GlobalMart |

---

### Integration Points

**GoodData AI Knowledge document API — the one new external surface.**
`{POST,PUT,GET,DELETE} /api/v1/ai/workspaces/{parent_workspace_id}/knowledge/documents`, reached
only from `knowledge_docs.py`. `PUT` with `multipart/form-data` (`file`, `title`, repeated
`scopes`) is the upsert primitive; `GET` is cursor-paginated and returns local + inherited + org
documents, so the reconciler filters to local-and-ours before comparing. Marked Experimental
(shipped 2026-03-26) — the module carries the consulted API date in its docstring, per the spec's
risk row.

**Raw REST, not the SDK.** `gooddata-python-sdk` models no knowledge document (FEAT-008 verified
the client surface; the notes confirm it is only in `api-client-tiger`'s generated
`KnowledgeAi`). STEERING § Coding Standards requires the gap be noted in a comment — it is, at
the single call site. Transport is `requests`, already a dependency and already used for raw REST
in `preflight.py`; multipart rules out `gd_agents.transport.Host`'s urllib helper.

**`config.py` / `sdk_client.py` (FEAT-001/002).** `--target <profile>` resolves through
`load_profile`; host, token and `parent_workspace_id` come from `TargetProfile` unchanged. No new
profile field: everything this feature needs is already there. `validate_for_publish` is **not**
reused — it checks warehouse keys this publish does not need; `knowledge_docs` asserts only
`host`, `token` and `parent_workspace_id`.

**`preflight.py` (FEAT-002).** The org-identity guard (`check_organization`) runs before any
write, so a mistyped `--target` cannot upload the corpus into the wrong org. This is the same
guard that caught the wrong `organization_id` during FEAT-002.

**`layout_io.read_tree` + `counts.py` (FEAT-001).** The coverage gate reads the committed parent
tree — never a live workspace (STEERING: the repo is the source of truth). `coverage` therefore
needs no `--target` and no network.

**`coverage.py` (FEAT-003).** Pattern reused, code not shared: same three-way
documented/excluded/uncovered classification, same `report → raise_for_report` split, same
`--strict` placeholder rule, same `PLACEHOLDER_REASONS` constant (imported from `domains.py`).
`CoverageReport` itself is not extended — it is keyed by dashboards/visualizations/AI objects and
owned by FEAT-003.

**`knowledge.py` (FEAT-008).** Sibling channel, no code dependency beyond the corrected
docstring. The two channels are kept apart by rule: a fact stated in a memory item is referenced
from the corpus by item id rather than restated, and `build` warns (never fails) when a corpus
section reproduces a memory item's `instruction` verbatim.

**`rebuild.py` (FEAT-006).** New step `publish-knowledge-docs` inserted directly after
`publish-parent` (it writes to the parent workspace; children inherit at query time, so it is
independent of `split`). `step_runner` gains `_run_publish_knowledge_docs`. Absent corpus
directory → `StepStatus.SKIPPED` with `detail="no docs/knowledge-corpus/ — nothing to publish"`.
Corpus present and publish failing → `RebuildAbortedError`, like every other step. The retrieval
check is **not** in the chain: an LLM-in-the-loop assertion inside the cold-rebuild proof would
make the rebuild non-deterministic.

**`gd_agents.a2a.client.A2ALane` + `gd_agents.transport.Host`.** The retrieval harness reuses
these rather than adding a second AI-Assistant client: `Host(host, token)` plus
`A2ALane(...).ask(question)` already returns parsed answer text
(`answer_text` → `(text, kind)`). This is the only globalmart → gd_agents import; it is one-way
and confined to `retrieval.py`.

**CI.** `knowledge-docs build` and `knowledge-docs coverage --strict` join `normalize --check`,
`split --check` and `domains validate --strict` as offline pre-merge gates.
`knowledge-docs retrieval --target demo-cloud` is a separate job with a credentialed environment,
allowed to run post-merge or on-demand rather than blocking every PR.

---

### Test Strategy

**Unit — `corpus.py` (offline, `tests/fixtures/corpus/`)**
- Front matter: missing `kind`/`title`/`scope`/`owner` each fail naming the file and the key; an
  unknown key fails naming allowed keys (FEAT-008's `_FRONT_MATTER_KEYS` precedent).
- `kind` not in `DiataxisKind` fails listing the four valid values.
- A document with two top-level `#` headings fails (one document, one subject).
- A section over `MAX_SECTION_CHARS` / a document over `MAX_DOCUMENT_CHARS` fails naming the
  heading and the count; a section under `MIN_SECTION_CHARS` fails.
- A `##` inside a fenced code block is not a section boundary (the exact bug `knowledge.py`'s
  `in_fence` flag guards; re-asserted here, not inherited).
- `published_filename` is deterministic, collision-free across the fixture, and a collision
  between two source paths fails the build.
- `digest` is stable across two parses and changes when one character of body changes.

**Unit — `corpus_coverage.py`**
- A metric in the parent named by no `covers:` and no exclusion is `uncovered` and fatal.
- An exclusion with reason `TODO:` passes plain, fails `--strict`.
- A `covers:` pattern matching nothing is `unknown_covers` and fatal — the renamed-metric case.
- An exclusion pattern matching nothing is `unmatched_exclusions` and fatal — the stale-exclusion
  case (FEAT-003 learned this one the other way round).
- One object documented by two documents is fine and both filenames are reported.
- Regression pin: the real parent tree + the real corpus report zero uncovered
  (`tests/test_corpus_real.py`, the analogue of `test_domains_real.py`).

**Unit — `knowledge_docs.py` (a `FakeKnowledgeApi`, no host)**
- Publish rehearsal (no `--apply`) issues zero writes and reports every intended upsert — ADR
  002, asserted the way `test_publish.py` asserts it.
- Second publish with unchanged repo reports `changed is False` and every result `unchanged`
  (AC #3).
- A repo document absent from the org is `missing_in_org`; an org document with the prefix but no
  repo file is `orphaned_in_org`; a document with neither prefix nor `OWNER_SCOPE` is
  `foreign_left_alone` and appears in no other bucket. **This is the test that matters in this
  feature**, the counterpart of FEAT-008's
  `test_a_build_never_touches_an_item_it_does_not_own`.
- Listing returns scopes on some rows and not others → `is_ours()` still classifies correctly.
- Cursor pagination: a two-page listing is fully consumed.
- `numChunks` changing between publishes changes the report's `chunk_deltas` and nothing else —
  no assertion, no failure.
- Prune (`verify --prune --apply`) deletes exactly the orphans and nothing else.

**Unit — `retrieval.py` (a stubbed `A2ALane`)**
- Fact containment is casefolded and whitespace-insensitive; an answer paraphrasing around the
  fact string fails, an answer with different casing/spacing passes.
- Three failing attempts fail the suite; a pass on attempt three passes it.
- A question naming a document absent from the corpus, or one whose `anchor` is false, fails at
  load time — not at ask time, and not against a live host.
- **The coupling guard:** every `expect_facts` string must appear verbatim in its named document.
  Run inside `knowledge-docs build`, so editing a load-bearing sentence fails offline with the
  question id rather than silently degrading the live suite.

**Integration (live, `--target demo-cloud`, run by hand and in the credentialed CI job)**
- Publish the corpus to the parent; `GET /documents` lists exactly the repo's filenames plus
  whatever was there before.
- **Inheritance probe:** list `/api/v1/ai/workspaces/globalmart-finance/knowledge/documents` and
  assert the parent's owned documents appear. This is the live answer to the spec's third open
  question and is a task in its own right (§ Implementation Order, step 8) — if inheritance turns
  out to have exceptions, the fallback is `publish --per-child`, which loops the same upsert over
  `manifest.keys()`. Designing for that fallback now would be speculative; detecting it early is
  cheap.
- `knowledge-docs retrieval --target demo-cloud` green on the full question set.
- A cold-rebuild rehearsal (`rebuild --target <fresh>`) lists `publish-knowledge-docs` among the
  planned steps (AC #7).

**Manual / human judgement**
- Read three documents against the live workspace and confirm they are true — the check no gate
  can perform, and the one FEAT-008 left as its open task.
- Judge whether the assistant's answers are *useful*, not merely fact-containing. The suite
  protects against regression; it cannot establish quality.

---

### Total Effort Estimate

| Scale | Meaning |
|---|---|
| S | A few hours |
| M | 1–3 days |
| L | 1–2 weeks |
| XL | More than a sprint — consider splitting the feature |

**Overall:** L — and honestly at the top of that band, matching the spec's `l` appetite (2–6
weeks).

The tooling is four small modules plus wiring: `corpus.py` M, `corpus_coverage.py` M,
`knowledge_docs.py` M, `retrieval.py` M, and roughly six S-sized edits (CLI, rebuild, CONTRACT,
ADR, CI, the `knowledge.py` docstring) — call the machinery 8–10 working days including tests.

**The authoring is the feature and it is the larger half.** 28–36 documents covering 225
datasets, 1091 metrics, 384 visualizations and 32 dashboards, written so the coverage gate goes
green without `covers:` patterns degenerating into `"*"`. That is L on its own.

Two notes rather than more design:

- If this needs to fit a shorter cycle, the clean split is **FEAT-015a (machinery + a
  four-document seed corpus + coverage gate running in report-only mode)** and **FEAT-015b (the
  full corpus + coverage gate promoted to fatal + the retrieval suite)**. The gate must not be
  fatal before the corpus exists, or the repo cannot go green in between.
- Do not split `knowledge_docs.py` out as its own feature. It is 200 lines and it is meaningless
  without documents to publish.

---

### Implementation Order

1. **CONTRACT.md first** (S). Add `corpus.py`, `corpus_coverage.py`, `knowledge_docs.py`,
   `retrieval.py` to the module-ownership table as FEAT-015; add the five `knowledge-docs` CLI
   rows; add the three on-disk paths and `tests/fixtures/corpus/`; add the footnote that
   `AiSelection.knowledge_ids` and `ai_context`'s `knowledge` channel stay dormant and why.
   CONTRACT's own rule is that a shared name changes here first, in the same commit.
2. **`corpus.py` + `tests/fixtures/corpus/` + `test_corpus.py`** (M). Schema, parser, validator,
   filename derivation, digest. Offline, no host, no layout. Everything downstream consumes
   `CorpusDocument`, so this is the blocking dependency.
3. **`config/corpus.yaml` loader** (S). Inside `corpus.py`'s sibling concern or at the top of
   `corpus_coverage.py` — a strict loader modelled on `domains.load_domains`, importing
   `PLACEHOLDER_REASONS` rather than re-declaring it.
4. **Seed corpus — 4 documents** (M). One per Diátaxis kind: `reference/data-model-overview.md`,
   `explanation/revenue-definitions.md`, `how-to/refresh-the-warehouse.md`,
   `tutorial/from-empty-org-to-globalmart.md`. Enough to exercise every validator against real
   prose before the gate exists.
5. **`corpus_coverage.py` + `test_corpus_coverage.py`** (M), with the gate **report-only** at
   first. Run it against the real parent tree to size the authoring job honestly — the number of
   uncovered metrics is the estimate for step 9.
6. **`knowledge_docs.py` + `test_knowledge_docs.py`** (M). Client, `publish_corpus`,
   `verify_corpus`, ownership reconciliation, digest-based idempotency. `FakeKnowledgeApi` only;
   no live call yet.
7. **`cli.py` wiring** (S). `knowledge-docs build | publish | verify | coverage | retrieval`.
   `--apply` on `publish` and on `verify --prune`; `--strict` on `coverage`; `--check` nowhere
   (the build *is* the check — it validates committed files and produces no artifact, so there is
   nothing to be stale).
8. **First live publish + the inheritance probe** (S). `publish --target demo-cloud --apply` with
   the seed corpus, then list a child workspace's documents. Closes the spec's third open
   question with evidence. Do this before authoring 30 documents, not after.
9. **The full corpus** (L). Author to close the coverage report, group by group, in the order
   `metrics` → `data-model` → `dashboards/<domain>` (×12) → `domains` → `warehouse` →
   `ai-context` → `getting-started`. Fill `config/corpus.yaml` exclusions as they arise, each
   with a real sentence.
10. **Promote coverage to fatal + `--strict` in CI** (S). Only once step 9 is green locally.
11. **`config/corpus-questions.yaml` + `retrieval.py` + `test_retrieval.py`** (M). Eight to
    twelve questions over `anchor: true` documents. Wire the offline fact-containment guard into
    `knowledge-docs build` at the same time, so the question set cannot rot silently.
12. **`rebuild.py` step** (S). `publish-knowledge-docs` + `_run_publish_knowledge_docs` +
    `skip_knowledge_docs`, and the `test_rebuild.py` assertion that the step is planned and that
    a missing corpus is a named skip rather than an omission.
13. **`knowledge.py` docstring correction + ADR 008** (S). The record that the 2026-09-18 "no
    document API" finding is superseded, and the two-channel split written down in both places.
14. **CI wiring** (S). Two offline gates in the pre-merge job; the retrieval job separate and
    credentialed.

---

### Resolved Open Questions

**1. Module name and CLI subcommand group.** Four modules —
`corpus.py` (authoring model, offline), `corpus_coverage.py` (the gate),
`knowledge_docs.py` (the only API-touching module), `retrieval.py` (the answer-level harness) —
and the CLI group `globalmart knowledge-docs`, exactly as the acceptance criteria already write
it. Four modules rather than one because CONTRACT says "one module, one concern" and because the
API-isolation risk mitigation requires the endpoint to live behind exactly one import. The names
avoid `knowledge*` collision at the top level (`knowledge.py` is FEAT-008's) while
`knowledge_docs.py` stays obviously adjacent to it.

**2. Repurpose `knowledge_ids` / the `ai_context.py` knowledge channel stub? No.** Those stubs
were written for an in-layout knowledge object: `ai_context.filter_ai_context` *copies* selected
objects into each child, and `coverage.check_coverage` treats an unselected AI object as
uncovered. AI Knowledge documents are the opposite on both counts — they live outside the layout
tree, are written by their own API call, and reach children by read-time inheritance rather than
by being copied (research notes, § 1, consequence 2). Wiring `knowledge_ids` to this feature
would model a per-child copy that never happens and would make `domains validate` demand
coverage of objects that are not in the layout at all. Per-domain grouping is instead expressed
as `scopes` derived from front-matter `domains:` — the same information, on the channel that
actually carries it. Consequences: no edit to `domains.py` or `ai_context.py` in this feature's
commit, no CONTRACT type change, and a CONTRACT footnote recording that the stubs remain reserved
for a future in-layout knowledge object should the SDK ever model one.

**3. Answer-level validation question set.** A committed `config/corpus-questions.yaml` of 8–12
entries, each naming a question, the published filename it must surface, and one or more expected
fact strings. Two rules keep the coupling cheap:
*(a)* a question may only cite a document whose front matter carries `anchor: true`, so authors
know which sentences are load-bearing before they rewrite them; and
*(b)* `knowledge-docs build` fails offline if an `expect_facts` string no longer appears verbatim
in its document. So ordinary prose edits touch nothing, and editing an anchored fact fails
immediately, locally, naming the question — rather than degrading a live LLM suite that nobody
notices. Assertion is fact-containment with `--attempts 3`; nothing asserts exact match and
nothing asserts `numChunks`.

**4. `rebuild.py`: hard failure or warned gap?** Hard failure when there is a corpus to publish.
`publish-knowledge-docs` is a first-class `RebuildStep` after `publish-parent`, and a failure
raises `RebuildAbortedError` like every other step — goal-01's "no manual step" bar is met
literally rather than annotated. The only softening is an absent `docs/knowledge-corpus/`
directory (or an explicit `--skip-knowledge-docs`), which reports `StepStatus.SKIPPED` with the
reason in the report line. That keeps the chain honest during steps 2–8 of the implementation
order, when the machinery exists and the corpus does not, without ever leaving the gap unnamed.

**5. Does parent-level publish reach the 12 children cleanly?** Designed for inheritance
(`publish` writes once, to `profile.parent_workspace_id`), verified live at implementation step 8
by listing a child workspace's documents before any volume is authored. If inheritance has
exceptions, the fallback is a `publish --per-child` flag looping the identical upsert over
`manifest.keys()` — a flag, not a redesign, because `publish_corpus(workspace_id=...)` is already
parameterised by workspace. Not flagged as blocking: the probe is a ten-minute read-only call and
it gates nothing before step 8.

### [DECISION NEEDED]

- **Does the pre-merge CI gate get org credentials, and may an LLM-in-the-loop job block a
  merge?** This breakdown assumes **no**: the two offline gates (`build`, `coverage --strict`)
  are pre-merge, and `knowledge-docs retrieval` is a separate credentialed job run post-merge or
  on demand. If retrieval must block merges, the repository needs a `GLOBALMART_TOKEN__*` secret
  in the PR workflow and an accepted flake budget on top of `--attempts 3`. This is a policy call
  about the merge gate, not a design choice, and it changes step 14 only.
