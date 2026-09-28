---

## Technical Breakdown — FEAT-017: Per-target `knowledge_scope` for the AI Knowledge corpus

Implements [ADR 010](../decisions/010-knowledge-scope-per-target.md) on top of FEAT-015's
workspace-scoped publish path. The target profile gets a `knowledge_scope` key. `workspaces` is
the default and behaves as the code does today. `organization` means one upsert to the
organization-level endpoint. A publish under either scope also removes our documents from the
*other* level, in the same `--apply` run, so a stale local copy can never shadow a fresh
inherited one.

**Binding interfaces touched (CONTRACT.md is amended first, in the same commit as the code):**
`TargetProfile` gains one field, `config.py` gains `KnowledgeScope`, the `knowledge_docs.py`
ownership row widens to cover the organization endpoint, and the on-disk row for
`docs/knowledge-corpus/` stops saying "published to **every** workspace" as if that were
unconditional. **No CLI flag is added or removed.** The `knowledge-docs publish` / `verify` /
`retrieval` and `rebuild` rows keep their flags exactly as they are; only their `Feature` column
gains `(+017)`.

### Spike gate (before any `--apply` code)

The spec's precondition probe is a hard gate. Components C3–C7 assume the answers below. If the
probe contradicts any of them, the spec is revised before code is written (AC 9).

| # | Question | Assumed answer | Consumer if wrong |
|---|---|---|---|
| P1 | Does `/api/v1/ai/organization/knowledge/documents` exist, and do `PUT` (multipart, same `file`/`title`/repeated `scopes` fields), `GET` list (`size`, `pageToken`, `nextPageToken`), `GET {id}/download` and `DELETE {id}` behave like the workspace endpoints? | Yes, same shapes | C3 (`HttpKnowledgeApi`) |
| P2 | What `workspaceId` does an org-level document report, both in an org listing and in a workspace listing? | `null`/absent in both | C4 — `is_local_to(None)` is the locality test for the org level, so this decides whether prune and cleanup can see our org copy at all |
| P3 | Does an org listing include workspace-level documents? | No | C5 — harmless either way, because `remove_ours` filters on `is_local_to(level)`, but the report counts would be misleading |
| P4 | Does `GET /workspaces/{ws}/knowledge/search` return org-level chunks with no extra parameter? | Yes, per ADR 009 documentation | `retrieval.py`: no change if yes, a query parameter if no |
| P5 | What permission does the org endpoint need (org admin vs. workspace manage)? | Org `MANAGE` | [DECISION NEEDED] D1 below |

P1–P3 and P5 are read-only (`GET` only). P4 needs **one throwaway write**: an org-level document,
searched from a workspace, then deleted. The spec calls the probe "read-only" and also says
"publish one throwaway doc". Those two statements conflict, so it is raised as D2.

### Components

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|
| **C0 `scripts/probe_org_knowledge.py`** | One-shot probe for P1–P5, in the same style as `scripts/take_custody.py` (not registered in the CLI). By default it runs `GET`s only: an org listing, one workspace listing, and the permission/404 shape of each. The P4 write half runs only with `--apply`. It uploads `gm-probe__org-level.md`, which carries neither ownership marker so no reconcile can ever claim it, searches for a sentinel phrase from `--workspace-id`, and deletes the document in a `finally`. It prints a findings block that is pasted into ADR 010 and the `knowledge_docs.py` docstring with the date | New | S |
| **C1 CONTRACT.md amendment** | `TargetProfile` row for `knowledge_scope`, a `KnowledgeScope` paragraph (shaped like `WarehouseType`'s), `config.py` row `(+017)`, `knowledge_docs.py` row widened to `/api/v1/ai/{workspaces/{id}\|organization}/knowledge/...` plus the two new orchestrators, the on-disk `docs/knowledge-corpus/` row made scope-dependent, the `AiSelection.knowledge_ids` paragraph's "upserted into every workspace directly" qualified by "or once at organization level (ADR 010)", and `Feature` columns `(+017)` on `knowledge-docs publish`, `verify` and `rebuild` | Existing | S |
| **C2 `config.py`: `KnowledgeScope` + `TargetProfile.knowledge_scope`** | A new `StrEnum` and a new frozen field, default `WORKSPACES`. It is parsed from the YAML entry **only**, with no `GLOBALMART_*` env override, exactly as `data_owned` is read (rationale under Data Model). An unknown value raises `GlobalmartError` at profile-load time and names the supported values, mirroring `warehouse_type` | Existing | S |
| **C3 `knowledge_docs.HttpKnowledgeApi`: organization level** | Adds `ORGANIZATION_BASE = "/api/v1/ai/organization/knowledge"`. `workspace_id` becomes `str \| None`, and `None` addresses the org level. `base` switches on it. New classmethod `for_organization(profile)`. `for_profile(profile, workspace_id)` keeps its parent-defaulting behaviour unchanged, so no caller changes meaning. `search()` on an org-level instance raises `KnowledgeDocsError` ("search from a workspace", per ADR 010). `KnowledgeDocsError` gains `status: int \| None`, set from `HTTPError.code` in `_request`, so C5 can tell 404 ("nothing here") from 403 and from real failures | Existing | S |
| **C4 `publish_corpus` / `verify_corpus` level-parameterised** | `workspace_id: str \| None` on both, and on `_partition`. `None` means organization level, consistent with `RemoteDocument.is_local_to`'s existing handling. `KnowledgeDocsReport.workspace_id` becomes `str \| None`, a `level_label` property renders `"organization"` or the workspace id, and `summary_lines()` prints `level` instead of `workspace`. No behavioural change for a `str` argument, so every existing FEAT-015 test passes untouched | Existing | S |
| **C5 `knowledge_docs.remove_ours` — cross-level cleanup primitive** | Lists one level and selects documents that are `is_ours()` **and** `is_local_to(level)`. With `apply` it deletes each one and records it. Without `apply` it records each as planned (ADR 002). Foreign documents are listed in `foreign_left_alone` and never touched. It deletes *all* of ours at that level, not only orphans: at the abandoned level every copy of ours is by definition a shadow or a stale leftover. A 404 on the listing (workspace absent, or org endpoint absent) is `absent`, meaning nothing to clean, and is not a failure. A per-document delete failure is recorded, and cleanup continues through the rest | New | M |
| **C6 `knowledge_docs.publish_for_target` / `verify_for_target` — scope orchestrators** | The single place that turns `(profile, workspaces, narrowed)` into write levels and clean levels (table under Data Model). It runs `publish_corpus` on each write level, then `remove_ours` on each clean level. **Cleanup runs only if every write succeeded**: the copy being removed may be the only one that currently exists, so an org upsert that failed must never be followed by deleting the thirteen workspace copies. A narrowed publish (`--parent-only` / `--workspace-id` under `workspaces`) never cleans the org level, because removing the org copy after writing one workspace would leave twelve with nothing. The report names the deferral. `verify_for_target` reconciles the configured level(s) with `verify_corpus`, and prune stays at those level(s) (AC 6). It then reads the other level and reports our copies there as `other_level_ours`, a stale state that exits non-zero, without deleting anything. Both accept an `api_factory: Callable[[str \| None], KnowledgeApi]` for tests. `corpus_workspaces(manifest)` moves here from the duplicated lists in `cli.py` and `rebuild.py` | New | M |
| **C7 `knowledge_docs.check_scope_flags`** | `check_scope_flags(profile, *, parent_only: bool, workspace_id: str \| None) -> None` raises `KnowledgeScopeError(KnowledgeDocsError)` under `organization` when either flag is set. The message names the target, its scope and the flag, e.g. `target 'fresh-org' has knowledge_scope: organization — --parent-only addresses one workspace and has no meaning at organization level. Remove the flag, or set knowledge_scope: workspaces in config/targets.yaml.` The logic lives in the module because `cli.py` holds registration only | New | S |
| **C8 `cli.py`: `cmd_knowledge_docs_publish` / `cmd_knowledge_docs_verify`** | Calls `check_scope_flags` before any network call, then delegates to `publish_for_target` / `verify_for_target` and prints `ScopedCorpusReport.summary_lines()`. `_corpus_workspaces` shrinks to the arg-narrowing only (`--workspace-id` / `--parent-only`) over `knowledge_docs.corpus_workspaces(manifest)`. The per-workspace loops move into C6. Exit codes: 1 on any write failure, any cleanup failure, or (verify) any stale level including `other_level_ours`. `cmd_knowledge_docs_retrieval` is **unchanged**: `--workspace-id` there picks the workspace to search *from*, which is valid under both scopes | Existing | S |
| **C9 `rebuild.py`: `publish-knowledge-docs` step** | `_run_publish_knowledge_docs` calls `publish_for_target(..., narrowed=False, apply=True)` in place of its own workspace loop. It raises `GlobalmartError` on a write failure (unchanged) **or** on a cleanup failure (new, and the same "no partial success" rule). It returns a detail that leads with the scope, e.g. `scope=organization: 18 documents at organization level (18 upserts); workspace cleanup 13 levels, 0 deleted`. The `_plan` SKIPPED paths and their details are unchanged (AC 8). The stale comment "children inherit it at query time" is corrected | Existing | S |
| **C10 `config/targets.yaml` + docs** | Adds explicit `knowledge_scope: workspaces` on `demo-cloud` and `demo-cloud-rebuild`, commented "shared org — ADR 009/010; never `organization`". Adds `knowledge_scope: organization` to the commented `fresh-org` example, with a one-line note that it applies only to an org dedicated to GlobalMart. `usecases-ai` is left without the key, so the default path stays exercised by a real profile. Updates the `knowledge_docs.py` module docstring endpoint table with the org-level rows and the probe date. ADR 010 status goes Proposed → Accepted, with the probe findings appended | Existing | S |
| **C11 Tests** | Extends `tests/test_knowledge_docs.py`, `test_config.py`, `test_cli.py`, `test_rebuild.py` and `test_retrieval.py` (detail under Test Strategy). `FakeKnowledgeApi` gains a `level: str \| None = WORKSPACE` field used by `upsert_document` in place of the hard-coded `WORKSPACE`, and a `FakeOrg` holder maps level → `FakeKnowledgeApi` to act as the `api_factory` | Existing | M |

### Data Model

No tables, no new files on disk, and nothing added to the layout tree. The corpus stays outside
the layout (ADR 009). Everything below is in-memory Python.

#### `config.py`

```python
class KnowledgeScope(StrEnum):
    """Where the AI Knowledge corpus is published for a target (ADR 010)."""
    WORKSPACES = "workspaces"      # default: one upsert per GlobalMart workspace (ADR 009)
    ORGANIZATION = "organization"  # one upsert at org level — ONLY for an org dedicated to GlobalMart


@dataclass(frozen=True)
class TargetProfile:
    ...                                                    # every existing field unchanged
    #: FEAT-017. Read from the YAML entry only — never from the environment. Widening a
    #: publish's blast radius to every workspace in an org is a reviewed, committed decision,
    #: not something a stray exported variable should be able to do.
    knowledge_scope: KnowledgeScope = KnowledgeScope.WORKSPACES
```

Parsing in `load_profile`:

```python
raw_scope = str(entry.get("knowledge_scope") or KnowledgeScope.WORKSPACES.value)
try:
    knowledge_scope = KnowledgeScope(raw_scope)
except ValueError as error:
    supported = ", ".join(s.value for s in KnowledgeScope)
    raise GlobalmartError(
        f"Profile {name!r} has unsupported knowledge_scope {raw_scope!r}. Supported: {supported}."
    ) from error
```

**Why no env override** (the only field in `load_profile` besides `data_owned` and
`datasource_secret_env` without one): `data_owned` sets the precedent for opt-in flags that
widen what a command may destroy or reach. ADR 010's "Infer the scope" row rejects anything that
changes the blast radius without a reviewed decision, and an env var in a long-lived shell is
exactly that kind of unreviewed change.

CONTRACT.md `TargetProfile` table, new row:

| Field | Type | Added by |
|---|---|---|
| `knowledge_scope` | `KnowledgeScope`, default `WORKSPACES`. YAML only, no env override. Unknown value raises at profile-load | FEAT-017 |

#### `knowledge_docs.py`: types

```python
ORGANIZATION_BASE = "/api/v1/ai/organization/knowledge"   # new, beside WORKSPACE_BASE

#: `None` is the organization level, everywhere in this module — the same convention
#: `RemoteDocument.is_local_to` already uses for documents read from a workspace listing.
LevelId = str | None
ApiFactory = Callable[[LevelId], KnowledgeApi]


class KnowledgeDocsError(GlobalmartError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status                         # HTTP status when the host answered


class KnowledgeScopeError(KnowledgeDocsError):
    """A flag that has no meaning under the target's knowledge_scope."""


@dataclass(frozen=True)
class HttpKnowledgeApi:
    host: str
    token: str
    workspace_id: str | None                         # was `str`; None = organization level

    @classmethod
    def for_organization(cls, profile: TargetProfile) -> HttpKnowledgeApi: ...

    @property
    def base(self) -> str:                           # ORGANIZATION_BASE when workspace_id is None
        ...


@dataclass
class KnowledgeDocsReport:                           # existing; two changes only
    workspace_id: str | None = ""                    # was `str`
    @property
    def level_label(self) -> str: ...                # "organization" | the workspace id


@dataclass
class CleanupReport:
    """One level being vacated: what of ours was there, and what became of it."""
    workspace_id: LevelId
    applied: bool
    planned: tuple[str, ...] = ()                    # ours+local, listed (rehearsal: would delete)
    deleted: tuple[str, ...] = ()                    # actually deleted (apply only)
    failed: tuple[tuple[str, str], ...] = ()         # (filename, error) per failed delete
    foreign_left_alone: tuple[str, ...] = ()
    absent: bool = False                             # listing 404 -> nothing to clean, not a failure
    error: str | None = None                         # listing failed for any other reason

    @property
    def level_label(self) -> str: ...
    @property
    def incomplete(self) -> bool:                    # failed or error; `absent` is complete
        ...


@dataclass
class ScopedCorpusReport:
    """What `knowledge-docs publish|verify` and the rebuild step print and assert on."""
    target: str
    scope: KnowledgeScope
    applied: bool
    levels: list[KnowledgeDocsReport]                # one per configured level (1 or 13; 1 if narrowed)
    cleanup: list[CleanupReport]                     # the other level(s)
    cleanup_deferred: str | None = None              # e.g. "narrowed publish (--parent-only)",
                                                     #      "write failed at organization level"
    @property
    def failed(self) -> tuple[str, ...]: ...         # "<level>: <filename>" for every failed upsert
    @property
    def cleanup_incomplete(self) -> tuple[str, ...]: ...  # level labels with incomplete cleanup
    @property
    def ok(self) -> bool: ...                        # not failed and not cleanup_incomplete
    def summary_lines(self) -> list[str]: ...        # first line: f"knowledge_scope   : {scope}"
```

#### `knowledge_docs.py`: functions

```python
def corpus_workspaces(manifest: DomainManifest) -> list[str]:
    """[parent] + every domain workspace, manifest order — today's duplicated lists, once."""

def publish_corpus(api, documents, *, workspace_id: LevelId, target="", apply=False) -> KnowledgeDocsReport
def verify_corpus(api, documents, *, workspace_id: LevelId, target="", prune=False, apply=False) -> KnowledgeDocsReport
    # signatures otherwise unchanged; `str` callers behave exactly as today

def remove_ours(api: KnowledgeApi, *, workspace_id: LevelId, apply: bool) -> CleanupReport

def check_scope_flags(profile: TargetProfile, *, parent_only: bool, workspace_id: str | None) -> None

def publish_for_target(
    profile: TargetProfile,
    documents: list[CorpusDocument],
    *,
    workspaces: Sequence[str],        # already narrowed by the caller under `workspaces`
    narrowed: bool,
    apply: bool,
    api_factory: ApiFactory | None = None,   # default: HttpKnowledgeApi.for_profile / for_organization
) -> ScopedCorpusReport

def verify_for_target(
    profile, documents, *, workspaces: Sequence[str], narrowed: bool,
    prune: bool, apply: bool, api_factory: ApiFactory | None = None,
) -> ScopedCorpusReport               # cleanup entries are always applied=False here
```

#### Level resolution (`publish_for_target` / `verify_for_target`)

| `knowledge_scope` | narrowed? | Write / reconcile levels | Clean levels (publish) / `other_level_ours` (verify) |
|---|---|---|---|
| `workspaces` | no | the 13 from `corpus_workspaces` | `[None]` (organization) |
| `workspaces` | yes (`--parent-only` / `--workspace-id`) | the 1 named | none. `cleanup_deferred = "narrowed publish"`. Verify still *reports* org-level ours |
| `organization` | n/a (C7 rejects the flags) | `[None]` | the 13 from `corpus_workspaces` |

#### Write-then-clean ordering and failure semantics

1. List and upsert every write level (`publish_corpus`). Failures are recorded per document, and
   the remaining documents and levels continue, exactly as today.
2. If `report.failed` is non-empty, **no cleanup runs**: `cleanup_deferred = "write failed at
   <level>"`. Whatever copies exist at the other level stay as the only working copy.
3. Otherwise run `remove_ours` on each clean level, continuing through every level when one fails.
4. Exit / chain result: `ok` is False if (1) failed **or** (3) left any level `incomplete`. The
   report lists deleted, planned and still-present filenames per level, so the next
   `verify --prune` or `publish --apply` knows what remains.

This resolves the spec's third open question. CONTRACT § Errors ("no partial success reported as
success") is binding, so a half-finished cleanup is a **non-zero exit with a complete report**.
It is not a softer partial-success state. The "named, not absent" spirit of ADR 009 is kept by
the per-level report, not by the exit code.

**Rehearsal** (no `--apply`) runs steps 1–3 with `apply=False`: writes become `would-upsert`,
deletions become `planned`, and zero writes and zero deletes are issued. The other-level listing
is a read, so a rehearsal still shows the full planned migration (ADR 010: "a dry run lists it
as a planned deletion").

#### Report shape (printed)

```
knowledge_scope   : organization
target            : fresh-org
applied           : True
── write: organization ──────────────
documents         : 18
created           : 18
── cleanup: 13 workspace level(s) ───
globalmart          deleted 18
globalmart-finance  deleted 18
...
globalmart-risk     FAILED  2 of 18 (HTTP 500) — still present: gm-corpus__reference__a.md, ...
cleanup incomplete: globalmart-risk — run `globalmart knowledge-docs publish --target fresh-org --apply` again
```

### Integration Points

- **GoodData AI Knowledge REST API (experimental), organization level (new).**
  `PUT|GET /api/v1/ai/organization/knowledge/documents`, `GET .../documents/{id}/download`,
  `DELETE .../documents/{id}`. All raw REST in `knowledge_docs.py`, standard library only,
  because the gooddata-python-sdk models no knowledge document (STEERING § Coding Standards: the
  gap is already noted in the module docstring, and the docstring gains the org rows and the
  probe date). The shapes are **assumed identical** to the workspace endpoints until C0 confirms
  them (P1).
- **GoodData AI Knowledge REST API, workspace level (existing).** It is still the write path
  under `workspaces`. It becomes a *delete* path under `organization` (cleanup), which is a new
  kind of traffic from this module: FEAT-015 only ever deleted orphans via
  `verify --prune --apply`.
- **Workspace search** `GET /api/v1/ai/workspaces/{ws}/knowledge/search`. `retrieval.py` is
  unchanged if P4 holds. It already matches expected documents by filename, and `SearchResult`
  already carries `workspace_id`, which will be `None` for org-level hits and is not consulted
  for matching (ADR 010: "a hit must be matched by filename, not by where the document is
  stored").
- **`config/targets.yaml` / `config.load_profile`.** This is the only source of the scope.
  Existing profiles need no migration (AC 1).
- **`config/domains.yaml` via `load_domains`.** It supplies the 13 workspace ids as the write set
  under `workspaces` and the clean set under `organization`. A workspace outside the manifest is
  neither written nor cleaned. Under `organization` it still *sees* the corpus by inheritance,
  which is the point of ADR 010.
- **`rebuild.py` step chain.** `publish-knowledge-docs` keeps its position, its SKIPPED paths and
  its fail-the-chain rule. Only its runner and its detail string change. Observed while reading,
  and **out of scope** here: the step runs straight after `publish-parent`, before
  `publish-domains`. In a cold rebuild under `workspaces`, the twelve domain workspaces do not
  exist yet when their upsert runs. Under `organization` this does not matter for the write. For
  cleanup, C5's 404 → `absent` rule makes the not-yet-existing workspaces clean no-ops rather
  than chain failures. The pre-existing `workspaces`-scope ordering should get its own ticket.
- **Ownership markers (ADR 009), unchanged.** `FILENAME_PREFIX = "gm-corpus__"`
  (`corpus.py`) OR `OWNER_SCOPE = "globalmart-corpus"`. Every delete this feature adds goes
  through `RemoteDocument.is_ours()` **and** `is_local_to(level)`. The probe's own document is
  named `gm-probe__…` with no `globalmart-corpus` scope precisely so that no reconcile can adopt
  it.
- **CONTRACT.md.** Amended in C1 (listed above). `tests/test_cli.py`'s staleness guard is
  unaffected because no flag changes.

### Test Strategy

All unit tests use the fakes: no live host (STEERING § AI Behavior). `FakeOrg` is a
`dict[LevelId, FakeKnowledgeApi]` whose `__call__(level)` is the `api_factory`. Every level's
fake records `upserts` / `deletes`, so "exactly one upsert, none to any workspace" is a direct
assertion.

**`tests/test_config.py`**
- `test_knowledge_scope_defaults_to_workspaces_when_absent`: AC 1. Existing profile YAML, no key.
- `test_knowledge_scope_organization_is_parsed`.
- `test_an_unknown_knowledge_scope_raises_at_profile_load`: value `"org"`. The message names
  both supported values.
- `test_knowledge_scope_ignores_the_environment`: `GLOBALMART_KNOWLEDGE_SCOPE=organization` set,
  profile still `WORKSPACES`.

**`tests/test_knowledge_docs.py`** (existing tests untouched and still passing, which proves C4
is behaviour-neutral for `str` levels)
- `test_the_organization_level_addresses_the_organization_endpoint`: `HttpKnowledgeApi(workspace_id=None).base == ORGANIZATION_BASE`. `for_organization(profile)` sets `None`.
- `test_search_from_the_organization_level_is_refused`.
- `test_publish_at_organization_level_treats_null_workspace_documents_as_local`: seeded with `workspace_id=None`. `unchanged` on the second run, and orphans are detected at org level.
- `test_under_organization_scope_exactly_one_level_is_written`: AC 2. `FakeOrg[None].upserts == [all filenames]`, and every workspace fake has `upserts == []`.
- `test_default_scope_writes_every_workspace_and_nothing_at_org_level`: AC 1. 13 levels written, `FakeOrg[None].upserts == []`.
- `test_moving_to_organization_removes_our_workspace_copies_in_the_same_run`: AC 4. Our docs are seeded in all 13 fakes. After `publish_for_target(apply=True)`, each workspace fake's `deletes` covers exactly our ids.
- `test_moving_to_workspaces_removes_our_organization_copy_in_the_same_run`: AC 5.
- `test_cleanup_never_touches_a_foreign_document_at_either_level`: a spec risk. `handbook.pdf` with no markers is seeded at org level **and** in `globalmart-finance`, plus a colliding-looking `net-revenue.md` without the prefix. It survives both scope directions and appears in `foreign_left_alone`.
- `test_cleanup_is_skipped_when_the_write_failed`: the org-level upsert is made to fail (monkeypatched, as in the existing flaky test). No workspace fake sees a delete, `cleanup_deferred` names the level, and `ok` is False.
- `test_a_partial_cleanup_fails_loudly_and_names_what_remains`: `globalmart-risk`'s delete raises. The other 12 are still cleaned, `cleanup_incomplete == ("globalmart-risk",)`, `ok` is False, and the still-present filenames are in the report.
- `test_an_absent_workspace_is_a_clean_no_op`: listing raises `KnowledgeDocsError(status=404)`. The level is `absent=True` and not `incomplete`.
- `test_a_forbidden_level_is_incomplete`: listing raises with `status=403`. The behaviour depends on the D1 answer; the default recommendation is asserted.
- `test_a_rehearsal_lists_planned_deletions_and_issues_none`: ADR 002 / ADR 010.
- `test_a_narrowed_publish_never_cleans_the_organization_level`: `narrowed=True`, `FakeOrg[None].deletes == []`, and `cleanup_deferred` is set.
- `test_verify_prune_under_organization_deletes_only_org_level_orphans`: AC 6. An org orphan, a workspace-level copy of ours and a foreign doc at org are all seeded. Only the org orphan is deleted, and the workspace copy is reported in `other_level_ours`, which makes the result stale.
- `test_check_scope_flags_rejects_parent_only_and_workspace_id_under_organization`: AC 3. Both flags are rejected, the message contains the target name and `knowledge_scope: organization`, and both flags are accepted under `workspaces`.

**`tests/test_cli.py`**
- `test_knowledge_docs_publish_under_organization_rejects_parent_only` and `..._workspace_id`: AC 3. Non-zero exit, stderr names the scope, and the API factory is never constructed (monkeypatch `HttpKnowledgeApi` to raise if built). This proves no network call happens.
- Parser flags for `knowledge-docs publish|verify|retrieval` and `rebuild` are unchanged. The existing CONTRACT-row test covers this, and no new assertion is needed.

**`tests/test_rebuild.py`**
- `test_publish_knowledge_docs_detail_names_the_scope`: AC 8, both scopes, with a fake factory injected by monkeypatching `knowledge_docs.HttpKnowledgeApi`.
- `test_publish_knowledge_docs_skip_semantics_are_unchanged`: no corpus dir, and `--skip-knowledge-docs`. Both are SKIPPED with today's details.
- `test_a_failed_cleanup_fails_the_chain`: the new failure mode is raised as `GlobalmartError`, not swallowed.

**`tests/test_retrieval.py`**
- `test_an_organization_level_hit_satisfies_a_question`: `SearchResult(workspace_id=None, filename=<expected>)` passes. The unit-level half of AC 7.

**Manual / live (explicitly requested runs only, per STEERING § AI Behavior)**
1. C0 probe, read-only half, against the target chosen in D2: record P1–P3 and P5.
2. C0 probe, `--apply` half (P4), only after D2 is answered: record whether workspace search returns the org chunk.
3. On a dedicated org with `knowledge_scope: organization`: run `knowledge-docs publish` as a rehearsal first (planned deletions listed), then `--apply`, then `verify`. Expect 0 stale.
4. `knowledge-docs retrieval --target <dedicated> --workspace-id globalmart-finance`: AC 7 live. Every question passes against org-level chunks.
5. demo-cloud regression: `knowledge-docs publish --target demo-cloud` rehearsal, with an output diff against the pre-feature run. The only additions are the `knowledge_scope : workspaces` line and an org-level cleanup section with 0 planned.

### Total Effort Estimate

| Scale | Meaning |
|---|---|
| S | A few hours |
| M | 1–3 days |
| L | 1–2 weeks |
| XL | More than a sprint — consider splitting the feature |

Per component: C0 S, C1 S, C2 S, C3 S, C4 S, C5 M (lower end), C6 M (lower end), C7 S, C8 S,
C9 S, C10 S, C11 M. Most of the work is in C5/C6 and their tests. The rest is small, because
`publish_corpus` and `RemoteDocument.is_local_to` already treat the level as a parameter and
`None` as organization.

**Overall:** M. That is 2–3 days of build, consistent with the spec's `s` appetite (1–3 days),
**excluding** time blocked on the C0 probe and on D1/D2. If P1 or P4 comes back negative (no org
endpoint, or search does not surface org chunks), the feature stops at C0 and the spec is revised.
That outcome is the spike gate working, not an overrun.

**[DECISION NEEDED] D1 — org-level unreadable under the default `workspaces` scope.** The
cleanup and `verify` now read the org level on every default-scope publish, including
demo-cloud. If the token lacks org-level permission (403), AC 1 ("behaviour unchanged") argues
against failing a publish that works today. *Recommendation:* under `workspaces`, a **403** on
the org-level listing yields a `CleanupReport` with `error` set and a loud
`org-level cleanup SKIPPED — token cannot read organization knowledge (HTTP 403)` line, but
**does not** fail the publish, because a token that cannot read the org level cannot have
written our org copy either. Under `organization`, a 403 on the write level is a hard failure as
usual. A **404** is `absent` under both scopes. The alternative is to fail loudly always and
require org-read permission for every publish. P5 in the probe supplies the evidence either way.

**[DECISION NEEDED] D2 — where the P4 probe write runs.** P4 needs one org-level document to
exist briefly, and that contradicts the spec's "read-only probe" wording. An org-level document
is visible to **every** workspace in the org, which is ADR 009's exact objection to demo-cloud.
*Recommendation:* run the whole probe against `usecases-ai` only if that org is confirmed to hold
nothing but GlobalMart. Otherwise use a fresh throwaway org, which also becomes the first profile
with `knowledge_scope: organization`. Never run it against demo-cloud. The document carries no
ownership marker and is deleted in a `finally`. The user must name the org and approve the
`--apply` run explicitly.

### Implementation Order

1. **C0 probe script (read-only half)**, and record P1–P3 and P5. **Gate:** if the org endpoint
   is absent or differs in shape, stop and revise the spec (AC 9).
2. **D1 and D2 answered.** Then run the C0 `--apply` half for P4. **Gate:** if workspace search
   does not return org chunks, stop and revise the spec (`retrieval.py` would need a change and
   AC 7's premise fails).
3. **C1 CONTRACT.md + C2 `config.py`**, in the same commit (CONTRACT rule: change the shared type
   here first). This includes the `test_config.py` cases.
4. **C3 `HttpKnowledgeApi` organization level**, plus `KnowledgeDocsError.status`, with its unit tests.
5. **C4 `publish_corpus` / `verify_corpus` accept `None`**, with `KnowledgeDocsReport.level_label`.
   The existing test suite must pass unchanged.
6. **C5 `remove_ours`**, and its extension of `FakeKnowledgeApi` (the `level` field) plus `FakeOrg`.
7. **C6 `publish_for_target` / `verify_for_target` / `corpus_workspaces`**, covering the level
   table, write-then-clean ordering, narrowed deferral, and the D1 behaviour. Carries the bulk of
   the C11 knowledge_docs tests.
8. **C7 `check_scope_flags`**, with its test.
9. **C8 `cli.py`**: rewire publish/verify onto C6/C7 and shrink `_corpus_workspaces`, with the
   `test_cli.py` cases.
10. **C9 `rebuild.py`**: runner onto `publish_for_target`, scope in the detail, cleanup failure
    fails the chain, and the stale comment fixed, with the `test_rebuild.py` cases.
11. **`test_retrieval.py` org-level hit** (C11 remainder).
12. **C10 `targets.yaml`, module docstring, ADR 010 → Accepted** with the probe findings.
13. **Manual live checks 3–5**, on the dedicated org and demo-cloud (rehearsal), only when the
    user explicitly requests the run.

---
