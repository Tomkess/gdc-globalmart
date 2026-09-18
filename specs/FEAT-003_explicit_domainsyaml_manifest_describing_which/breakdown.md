## Technical Breakdown — FEAT-003: Explicit domains.yaml manifest describing which dashboards and visualizations belong to each of the 12 domains, bootstrapped from the existing viz-prefix convention and coverage-checked

> **Continuity with FEAT-001/002.** No new package, no new CLI, no new config directory. This extends `src/globalmart/` (console script `globalmart`), reuses `read_tree()` from `layout_io.py`, `GlobalmartError` from `config.py`, `count_objects()` / `ObjectCounts` from `counts.py`, and **extends** FEAT-002's `traversal.py` rather than adding a second enumerator of model internals. `config/domains.yaml` sits beside `config/targets.yaml`.

> **The single invariant this feature exists to enforce.** The predecessor's splitter assigned a dashboard to a domain only when *every* visualization on it matched `viz_<domain>_`, so a dashboard mixing Sales and Finance tiles matched nothing, was dropped, and produced no error. Here, membership is data, coverage is computed over the whole parent, and any dashboard or visualization that is in no domain and on no explicit exclusion list fails the command. The prefix convention survives in exactly one function, `domain_bootstrap.bootstrap_manifest()`, which runs once.

---

### Components

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|
| `config/domains.yaml` | The deliverable: `version`, id/name templates, 12 `domains` entries, an optional `shared` block, and an `unassigned` allow-list with reasons. Committed, hand-reviewed, deterministically ordered. Full schema and a worked example under **Data Model**. | New (committed, generated once then hand-owned) | M |
| `src/globalmart/domains.py` | Schema and I/O. Frozen dataclasses `DomainManifest`, `Domain`, `AiSelection`, `Exclusion`, `SharedSelection`. `load_domains(path: Path) -> DomainManifest` parses **strictly** — an unknown mapping key anywhere raises `DomainManifestError` naming the key and its dotted path, so a typo'd `dashboard:` never silently means "no dashboards". `dump_domains(manifest, path) -> None` writes canonical YAML (domains sorted by `key`, every id list sorted lexically, `yaml.safe_dump(sort_keys=False, default_flow_style=False, allow_unicode=True, width=100, indent=2)` with an explicit key order so the file reads top-down). `resolve_workspace_id(manifest, domain)` and `resolve_workspace_name(manifest, domain)` apply the templates. Also carries the accessors FEAT-004 consumes so no caller re-derives them: `DomainManifest.by_key(key) -> Domain`, `DomainManifest.keys() -> tuple[str, ...]`, `DomainManifest.resolve_workspace_name(domain) -> str` (method form of the helper above) and `DomainManifest.unassigned_ids() -> frozenset[str]`, the flattened exclusion ids across `unassigned.dashboards`, `unassigned.visualizations` and `unassigned.ai` for callers that only need membership. | New | M |
| `src/globalmart/traversal.py` | Extended with `iter_dashboard_insight_refs(model) -> Iterator[tuple[str, str]]`, yielding `(dashboard_id, visualization_object_id)` for every visualization a dashboard's layout references. Implemented as a generic recursive walk of `dashboard.content` collecting `{"identifier": {"id": <id>, "type": "visualizationObject"}}` — **not** an assumed `sections[].items[].widget` shape — so nested layouts, drill targets and rich-text widgets are all caught. Also `dashboard_visualization_ids(model, dashboard_id) -> set[str]`. | Existing — modified | M |
| `src/globalmart/coverage.py` | The enforcement. `check_coverage(model, manifest) -> CoverageReport` classifies every dashboard id, visualization object id and AI-context object id in the parent into assigned / shared / excluded / **uncovered**, resolves visualization coverage through `iter_dashboard_insight_refs`, detects manifest ids absent from the parent — including every `ldm_include` dataset id, checked against `model.ldm.datasets` — flags multi-homed objects, and computes per-domain counts. `ldm_include` ids are validated for existence and counted per domain, but they never satisfy coverage of a dashboard, visualization or AI object: they widen a child's LDM, they do not declare membership. `raise_for_report(report, *, strict: bool) -> None` raises `CoverageError` when anything is uncovered or unknown, and additionally on placeholder reasons under `strict`. Pure, host-free, no I/O. | New | L |
| `src/globalmart/domain_bootstrap.py` | The one-time generator. `SEED_DOMAINS: tuple[tuple[str, str], ...]` — the 12 `(key, label)` pairs — and `bootstrap_manifest(model, *, seed=SEED_DOMAINS) -> tuple[DomainManifest, BootstrapReport]`. Matches `viz_<key>_` prefixes longest-key-first (so `store_ops` wins over a hypothetical `store`), assigns a dashboard to **every** domain any of its referenced visualizations belongs to, puts prefix-matching visualizations on no dashboard into that domain's `visualizations` list, and dumps everything else — unmatched visualizations, unreferenced dashboards, every AI-context object — into `unassigned` with a `TODO:` reason. Module docstring states this is one-time seed data and that no runtime code may import `SEED_DOMAINS`. | New | M |
| `src/globalmart/cli.py` | Adds the `domains` group: `globalmart domains validate [--manifest config/domains.yaml] [--layout layouts/workspaces/globalmart] [--strict] [--format table\|json]` (exit 1 on any coverage or unknown-id failure) and `globalmart domains bootstrap [--layout ...] [--out config/domains.yaml] [--dry-run] [--force]`. `--dry-run` is correct here per ADR 002 — `bootstrap` writes only a local file and never touches a host; `--force` is required to overwrite an existing manifest. | Existing — modified | S |
| `tests/fixtures/mini_globalmart/` | Extended with a second dashboard whose tiles span two domains, one visualization on no dashboard, one visualization matching no prefix, and one memory item — the four shapes the coverage rules exist for. | Existing — modified | M |
| `tests/fixtures/domains/` | Six small manifests: `valid.yaml`, `mixed_domain_dashboard.yaml`, `missing_coverage.yaml`, `unknown_id.yaml`, `empty_reason.yaml`, `unknown_key.yaml`. Plus `bootstrap_golden.yaml`, the generator's expected output on the fixture tree. | New | M |
| `tests/` (4 new modules, see Test Strategy) | `test_domains.py`, `test_coverage.py`, `test_domain_bootstrap.py`, `test_single_source_of_domains.py`; `tests/test_traversal.py` and `tests/test_cli.py` extended. | New / modified | M |
| `docs/domains.md` | One page: the schema field by field, the many-to-many rule, the deny-by-default AI rule, how to add a domain (one file, one edit), and the statement that the prefix convention is dead after bootstrap. | New | S |
| `specs/decisions/003-explicit-domain-membership.md` | ADR recording many-to-many membership, coverage-or-explicit-exclusion, and deny-by-default AI scoping — per STEERING § AI Behavior, non-obvious choices become ADRs. | New | S |

---

### Data Model

**`config/domains.yaml` — schema v1.**

Top level:

| Key | Type | Required | Meaning |
|---|---|---|---|
| `version` | `int` | yes | Schema version. `1` today; a loader seeing anything else raises rather than guessing. |
| `parent_workspace_id` | `str` | yes | The source workspace, `globalmart`. Asserted equal to `TargetProfile.parent_workspace_id` by the validator. |
| `workspace_id_template` | `str` | yes | Default `"globalmart-{key_kebab}"`. `{key_kebab}` is the domain key with `_` → `-`. |
| `workspace_name_template` | `str` | yes | Default `"GlobalMart — {label}"`. Rendered value is what FEAT-004 passes to `publish_workspace(..., workspace_name=...)` (FEAT-002's `--workspace-name`). |
| `domains` | `list[Domain]` | yes | Exactly the domains that exist. Order in file is sorted by `key`. |
| `shared` | `SharedSelection` | no | Objects that belong in **every** child. Counts as coverage. |
| `unassigned` | `UnassignedSelection` | no | Explicit, reasoned exclusions. Counts as coverage. |

`Domain`:

| Key | Type | Required | Meaning |
|---|---|---|---|
| `key` | `str` | yes | snake_case, matches `^[a-z][a-z0-9_]*$`, unique. |
| `label` | `str` | yes | Human label, e.g. `Sales`. Unique. Feeds `workspace_name_template`. |
| `description` | `str` | yes | One sentence, for `docs/domains.md` and the child workspace description. |
| `workspace_id` | `str` | yes | Written out explicitly even though it is derivable — the validator asserts it equals the template's output, so the file stays greppable and the convention stays honest. Unique, ≠ `parent_workspace_id`. |
| `workspace_name` | `str` | no | Per-domain override of the rendered template. |
| `dashboards` | `list[str]` | yes | Analytical dashboard ids. May be empty only if `visualizations` is non-empty. |
| `visualizations` | `list[str]` | no | Visualization object ids that belong to this domain but sit on **no** listed dashboard. Visualizations reachable from a listed dashboard are covered automatically and must not be repeated here (the validator reports redundant entries). |
| `ai` | `AiSelection` | no | Per-domain AI context. Absent means this domain gets no AI context. |
| `ldm_include` | `list[str]` | no | Dataset ids to include in this child's LDM **beyond** what FEAT-004's closure reaches, so the child has room to author new metrics and visualizations on tables today's dashboards do not touch. FEAT-004 adds them to its closure seed and pulls their join ancestors in exactly as for any other retained dataset. Every id must exist in the parent's `ldm.datasets` or validation fails. This is an **LDM concern only**: it is never coverage of a dashboard, visualization or AI object, and it is not the `shared:` block — `shared:` declares analytics that belong in every child, `ldm_include` declares tables one child wants headroom on. |

`AiSelection`: `memory_item_ids: list[str]`, `memory_item_tags: list[str]` (a memory item carrying any listed tag is included — the one place a rule rather than an id list is allowed, because AI memory is expected to grow), `parameter_ids: list[str]`, `agent_ids: list[str]`, `knowledge_ids: list[str]` (AI-knowledge objects; STEERING § Portability Contract names AI knowledge as one of the four channels that must travel *and* be filtered per domain, so it is selected here exactly like the other three rather than left to FEAT-004).

`SharedSelection`: `dashboards: list[str]`, `visualizations: list[str]`, `ai: AiSelection`.

`UnassignedSelection`: `dashboards: list[Exclusion]`, `visualizations: list[Exclusion]`, `ai: list[Exclusion]`, where `Exclusion` is `{id: str, reason: str}`. Under `--strict`, a `reason` that is empty, whitespace, or case-insensitively one of `TODO`, `TBD`, `n/a`, `none`, or that starts with `TODO:`, fails.

**Worked example** (abridged to two of the twelve domains, real ids in the shape the parent uses):

```yaml
version: 1
parent_workspace_id: globalmart
workspace_id_template: "globalmart-{key_kebab}"
workspace_name_template: "GlobalMart — {label}"

domains:
  - key: sales
    label: Sales
    description: Revenue, orders, pipeline and sales-rep performance across all channels.
    workspace_id: globalmart-sales
    dashboards:
      - dash_sales_overview
      - dash_sales_rep_performance
      - dash_exec_revenue_and_margin      # multi-homed with finance — the case the predecessor dropped
    visualizations:
      - viz_sales_orders_yoy_kpi          # used by AI search, sits on no dashboard
    ai:
      memory_item_ids:
        - mem_sales_definitions
      memory_item_tags:
        - domain/sales
      parameter_ids:
        - param_sales_fiscal_year_start
      agent_ids:
        - agent_sales_analyst
      knowledge_ids:
        - know_sales_playbook

  - key: store_ops
    label: Store Operations
    description: Store staffing, footfall, shrink and per-location operational KPIs.
    workspace_id: globalmart-store-ops     # key_kebab: store_ops -> store-ops
    dashboards:
      - dash_store_ops_daily
      - dash_store_ops_labor
    visualizations: []
    ai:
      memory_item_tags:
        - domain/store_ops
    ldm_include:                           # LDM headroom only — NOT coverage, and not `shared:`
      - dim_store                          # closure reaches neither today; both are wanted so a
      - dim_geo                            # store-coverage metric can be authored in the child

shared:
  dashboards: []
  visualizations: []
  ai:
    parameter_ids:
      - param_default_currency             # every child needs it; listing it 12× would be worse

unassigned:
  dashboards:
    - id: dash_eval_scratch_2026_05
      reason: Eval harness scratch dashboard left in the parent; belongs to no business domain.
  visualizations:
    - id: viz_untitled_copy_3
      reason: Duplicate of viz_sales_orders_yoy_kpi created during an LLM description pass.
  ai:
    - id: mem_org_onboarding_notes
      reason: Org-specific onboarding text with no analytical content; must not reach any child.
```

**Python model** (`domains.py`, all frozen dataclasses, list fields as `tuple[str, ...]` so a manifest cannot be mutated after load):

`Domain(key, label, description, workspace_id, workspace_name, dashboards, visualizations, ai, ldm_include)`
(`ldm_include: tuple[str, ...]`, default empty);
`AiSelection(memory_item_ids, memory_item_tags, parameter_ids, agent_ids, knowledge_ids)`;
`Exclusion(id, reason)`;
`SharedSelection(dashboards, visualizations, ai)`;
`UnassignedSelection(dashboards, visualizations, ai)`;
`DomainManifest(version, parent_workspace_id, workspace_id_template, workspace_name_template, domains, shared, unassigned, path)`.

**`DomainManifest` accessors** — the ergonomics FEAT-004 asked for, owned here so a consumer never re-derives
manifest truth:

| Method | Returns | Meaning |
|---|---|---|
| `by_key(key: str) -> Domain` | the domain | Raises `DomainManifestError` naming the key when it is not in the manifest. |
| `keys() -> tuple[str, ...]` | domain keys | In the manifest's canonical (`key`-sorted) order, so a consumer iterating it is deterministic by construction. |
| `resolve_workspace_name(domain: Domain) -> str` | the published display name | `domain.workspace_name` when set, otherwise `workspace_name_template` rendered with `label`. This is the only sanctioned way to produce the string passed to `publish_workspace(..., workspace_name=...)` — no caller concatenates `"GlobalMart — " + label` itself. |
| `unassigned_ids() -> frozenset[str]` | flattened exclusion ids | Every `Exclusion.id` across `unassigned.dashboards`, `unassigned.visualizations` and `unassigned.ai`, for callers that need membership only and not the reasons. The reasons stay reachable on `unassigned` itself. |

**`CoverageReport`** (`coverage.py`, dataclass — the object the CLI prints and every test asserts against):

| Field | Type | Meaning |
|---|---|---|
| `dashboards_total` | `int` | 32 on the real parent |
| `visualizations_total` | `int` | 384 on the real parent |
| `ai_objects_total` | `int` | memory items + parameters + agent personalities + AI-knowledge objects |
| `assigned_dashboards` | `dict[str, tuple[str, ...]]` | dashboard id → domain keys covering it |
| `assigned_visualizations` | `dict[str, tuple[str, ...]]` | viz id → domain keys (direct listing **or** via a listed dashboard) |
| `assigned_ai` | `dict[str, tuple[str, ...]]` | AI object id → domain keys |
| `multi_homed` | `dict[str, tuple[str, ...]]` | any object with ≥2 domain keys — reported, never an error |
| `shared_ids` | `tuple[str, ...]` | ids covered by the `shared:` block |
| `excluded` | `dict[str, str]` | id → reason, from `unassigned:` |
| `uncovered_dashboards` | `tuple[str, ...]` | **fatal** |
| `uncovered_visualizations` | `tuple[str, ...]` | **fatal** |
| `uncovered_ai` | `tuple[str, ...]` | **fatal** — deny-by-default means unclassified, not "goes nowhere quietly" |
| `unknown_ids` | `dict[str, str]` | manifest id → its dotted manifest path, for ids absent from the parent (including `domains[i].ldm_include[j]` entries missing from `ldm.datasets`) — **fatal** |
| `placeholder_reasons` | `dict[str, str]` | id → reason, for `TODO`/`TBD`/`n/a`/empty — fatal under `--strict` only |
| `redundant_visualizations` | `dict[str, tuple[str, ...]]` | listed under a domain but already covered by one of that domain's dashboards — warning |
| `cross_domain_tiles` | `dict[str, tuple[str, ...]]` | `(domain, dashboard)` → visualization ids referenced by that dashboard but not covered by that same domain; a preview of what FEAT-004's closure will have to pull in |
| `per_domain` | `dict[str, DomainCounts]` | per key: dashboards, visualizations (direct + via dashboards), memory items, parameters, agents |

**`DomainCounts`**: `dashboards: int`, `visualizations_direct: int`, `visualizations_via_dashboards: int`, `memory_items: int`, `parameters: int`, `agents: int`, `knowledge: int`, `ldm_include: int` (declared LDM datasets — printed beside the others so declared widening stays visible, never added to any coverage total).

**`BootstrapReport`** (`domain_bootstrap.py`): `matched_visualizations: int`, `unmatched_visualizations: tuple[str, ...]`, `dashboards_assigned: int`, `dashboards_unreferenced: tuple[str, ...]`, `ai_objects_parked: int`, `per_domain: dict[str, DomainCounts]`. Printed before the file is written, so the residue size is known before anyone commits it.

**Exceptions** (all subclasses of FEAT-002's `GlobalmartError`): `DomainManifestError` (parse/schema/uniqueness/template mismatch) and `CoverageError` (uncovered, unknown, or — under strict — placeholder reasons), the latter carrying the `CoverageReport` so the CLI can print the full picture alongside the failure.

No database, no warehouse schema. The persisted state this feature adds is one committed YAML file.

---

### Integration Points

- **FEAT-001** — `read_tree(Path("layouts/workspaces/globalmart"))` is the only way the parent is
  read. Object ids come from `model.analytics.analytical_dashboards[*].id`,
  `model.analytics.visualization_objects[*].id`, and the AI-context collections FEAT-001 task 31a
  added to the capture (`memoryItems`, parameters, agent personalities, AI knowledge). `GlobalmartError` is the
  exception base. Nothing here reads a live org — STEERING's first constraint.
- **FEAT-002** — `traversal.py` gains `iter_dashboard_insight_refs`; the existing generators are
  untouched and their tests must stay green. `resolve_workspace_name()` produces the string FEAT-004
  will pass to `publish_workspace(..., workspace_name=...)`, reconciling FEAT-002's `"GlobalMart — Sales"`
  example with this manifest's bare `label: Sales` — the template owns the joining, so the two
  features cannot disagree about the published name.
- **FEAT-004 (consumer)** — reads `load_domains()` and nothing else for membership. Its contract with
  this feature: a domain's object set is `dashboards` ∪ `visualizations` ∪ `shared.dashboards` ∪
  `shared.visualizations` ∪ `{viz reachable from all of those dashboards}`, and its AI context is
  exactly `domain.ai` ∪ `shared.ai` — AI selection is **nested** under `Domain.ai`, never flat, and
  `ai.memory_item_tags` is a rule (a memory item carrying any listed tag is in that domain) that a
  consumer must honour alongside the id lists. Separately, `domain.ldm_include` is an **LDM-only**
  declaration: FEAT-004 adds those dataset ids to its closure seed and pulls their join ancestors in
  like any other retained dataset's, and reports them apart from the closure-reached ones. It is
  never coverage, so it takes no part in the object set above. FEAT-004 reaches the manifest only through
  `by_key()`, `keys()`, `resolve_workspace_name()` and `unassigned_ids()`; it never renders the
  workspace-name template or flattens the exclusion lists itself. FEAT-004 must call `check_coverage`
  + `raise_for_report(strict=True)` before emitting anything, so a split cannot run against a stale
  manifest.
- **CLI** — `domains` becomes the third subcommand group beside `bootstrap`/`normalize` (FEAT-001)
  and `publish` (FEAT-002). `--dry-run` on `domains bootstrap` is ADR-002-compliant: its only write
  is a local file.
- **CI** — one job: `uv run globalmart domains validate --strict`. It is the mechanism that makes
  "the manifest is the single source of truth" survive contact with future PRs. It runs offline and
  needs no credentials.
- **Git** — `config/domains.yaml` is reviewed as a diff. Canonical ordering exists so that adding one
  dashboard to one domain is a one-line diff, not a reshuffle.

---

### Test Strategy

Everything offline, `uv run pytest tests/ -x -q`. No host, no credentials, no network. Fixtures are
`tests/fixtures/mini_globalmart/` (extended) plus `tests/fixtures/domains/*.yaml`.

**Unit — `tests/test_domains.py`**
- `load_domains(valid.yaml)` returns 2 domains (the fixture's scale) with tuple-typed id lists;
  round trip `load_domains → dump_domains → load_domains` is equal, and the dumped bytes are
  identical to the input when the input is already canonical.
- `unknown_key.yaml` (a domain carrying `dashboard:` instead of `dashboards:`) raises
  `DomainManifestError` naming the key and its path — the silent-typo class.
- Uniqueness: duplicate `key`, duplicate `label`, duplicate `workspace_id`, and a `workspace_id`
  equal to `parent_workspace_id` each raise.
- `workspace_id` not matching `workspace_id_template` raises; `store_ops` → `globalmart-store-ops`
  is asserted explicitly, because the snake/kebab split is the one place the convention can silently
  break.
- `resolve_workspace_name` on `label: Sales` with the default template yields `GlobalMart — Sales`
  (the exact string FEAT-002's breakdown names), and a per-domain `workspace_name` overrides it.
  Asserted on the `DomainManifest.resolve_workspace_name(domain)` method form, since that is the
  entry point FEAT-004 calls.
- `version: 2` raises rather than being parsed leniently.
- The consumer accessors: `by_key("sales")` returns the `sales` domain and `by_key("nope")` raises
  `DomainManifestError` naming the key; `keys()` returns the keys in canonical sorted order;
  `unassigned_ids()` equals the flattened set of every `Exclusion.id` across all three `unassigned`
  lists and is a `frozenset` (a caller cannot mutate the manifest through it).
- An `ai` block carrying `knowledge_ids` round-trips like the other three AI id lists and is present
  on the loaded `AiSelection`.
- `ldm_include` round-trips as a `tuple[str, ...]`, defaults to `()` when the key is absent, and
  sorts canonically on dump like every other id list.

**Unit — `tests/test_traversal.py`** (extended, not replaced)
- `iter_dashboard_insight_refs` on the fixture yields the known `(dashboard, viz)` pairs.
- A visualization reference planted in a **nested** layout and one in a drill definition are both
  found — the generic-walk requirement, asserted rather than assumed.
- A dashboard with zero visualization references yields nothing and does not raise.

**Unit — `tests/test_coverage.py`** (the core of the feature)
- **The predecessor-bug test:** a dashboard whose tiles are `viz_sales_*` and `viz_finance_*`, listed
  under both `sales` and `finance`. Coverage passes, `multi_homed` contains it with both keys, and
  neither the dashboard nor any of its tiles appears in `uncovered_*`. The predecessor dropped this
  dashboard silently; this test is the feature.
- A dashboard present in the parent and in no domain, no `shared`, no `unassigned` →
  `uncovered_dashboards` non-empty and `raise_for_report` raises `CoverageError` naming it.
- A visualization reachable only through a listed dashboard is covered without being listed;
  a visualization on no dashboard and in no list is uncovered and fatal.
- A manifest id absent from the parent lands in `unknown_ids` with its manifest path and is fatal.
- An `unassigned` entry with `reason: "TODO: classify"` passes plain validation and fails under
  `strict=True`; a real sentence passes both.
- An AI object in no domain, no `shared.ai`, no `unassigned.ai` → `uncovered_ai`, fatal. An AI object
  matched only by `memory_item_tags` is covered, and appears under exactly that domain — the
  no-cross-domain-leak assertion, expressed as "domain B's report contains zero of domain A's items".
- `cross_domain_tiles` is populated when a listed dashboard references a visualization assigned only
  to another domain, and empty for the clean fixture.
- `redundant_visualizations` flags a viz listed under a domain that already covers it via a dashboard.
- `ldm_include`: a dataset id absent from `model.ldm.datasets` lands in `unknown_ids` with its
  `domains[i].ldm_include[j]` path and is fatal; a valid one is counted in that domain's
  `DomainCounts.ldm_include` and changes **no** coverage outcome — a dashboard or visualization is
  neither covered nor uncovered because of it, and it does not make a domain that lists only
  `ldm_include` entries a non-empty domain.

**Unit — `tests/test_domain_bootstrap.py`**
- `bootstrap_manifest(fixture_model)` equals the committed `tests/fixtures/domains/bootstrap_golden.yaml`
  byte-for-byte after `dump_domains`, and running it twice into two paths yields identical bytes.
- Longest-prefix matching: a visualization id `viz_store_ops_headcount` is assigned to `store_ops`,
  not to a shorter key that is also a prefix.
- **ANY, not ALL:** a mixed-tile dashboard is assigned to both its domains. A test constructed as the
  predecessor's rule (ALL) would leave it unassigned; the assertion is that it appears under both.
- Every unmatched visualization, unreferenced dashboard and AI object appears under `unassigned`
  with a `TODO:`-prefixed reason — never omitted. The count matches `BootstrapReport`.
- The generated manifest passes `check_coverage` with `strict=False` and **fails** with
  `strict=True` — the guard that an unreviewed bootstrap cannot go green in CI.

**Static — `tests/test_single_source_of_domains.py`**
- Walk `src/globalmart/**/*.py` and `config/**` for each of the 12 keys and 12 labels; assert the
  only hits are `config/domains.yaml` and `src/globalmart/domain_bootstrap.py` (the sanctioned
  one-time seed). This is the mechanized version of "the predecessor had the domain list in four
  places".

**CLI — `tests/test_cli.py`** (extended)
- `domains validate` on `valid.yaml` + fixture tree exits 0 and prints the per-domain table;
  on `missing_coverage.yaml` exits 1 and names the uncovered dashboard.
- `domains validate --format json` emits a parseable `CoverageReport` dict.
- `domains bootstrap --dry-run` writes no file and prints the `BootstrapReport`.
- `domains bootstrap` against an existing `config/domains.yaml` without `--force` exits 1 without
  writing; with `--force` it overwrites.

**Guard against the real tree — `tests/test_domains_real.py`**
- Skipped cleanly until `layouts/workspaces/globalmart/` and `config/domains.yaml` both exist; then
  asserts 12 domains, `check_coverage` clean under `strict=True`, `dashboards_total == 32`,
  `visualizations_total == 384`, and that the 12 keys and the 12 child workspace ids are exactly the
  expected sets. This is the acceptance criterion the whole feature exists for, run in CI.

**Manual, once** — run `globalmart domains bootstrap --dry-run` against the real tree, read the
residue counts, triage them with the user, then generate, hand-edit and review the diff.

---

### Total Effort Estimate

| Scale | Meaning |
|---|---|
| S | A few hours |
| M | 1–3 days |
| L | 1–2 weeks |
| XL | More than a sprint — consider splitting the feature |

| Component | Effort |
|---|---|
| `domains.py` (schema, strict loader, canonical dumper, templates) | M |
| `traversal.py` extension (`iter_dashboard_insight_refs`) | M |
| `coverage.py` (`check_coverage`, `CoverageReport`, `raise_for_report`) | L |
| `domain_bootstrap.py` (seed, prefix matching, ANY-rule assignment, TODO parking) | M |
| `cli.py` (`domains validate` / `domains bootstrap`, report rendering) | S |
| Fixtures (`mini_globalmart` extension + 7 manifest fixtures) | M |
| Tests (5 modules new/extended) | M |
| `docs/domains.md`, ADR 003, CI job | S |
| **Human triage of the real residue and hand-review of the generated manifest** | M |

**Overall: M (2–3 days).** The code is small and entirely pure — no host, no SDK writes, one YAML
file. Two things will eat the time. First, `iter_dashboard_insight_refs`: the dashboard `content`
blob is the least regular part of the layout, and getting a generic walk right (nested layouts, drill
targets, rich-text) is the difference between real coverage and a number that looks right. Second,
the residue: 384 visualizations against 32 dashboards means a meaningful share sit on no dashboard,
and every one of them needs a domain or a written reason. That is human work, not code, and it is
the honest cost of replacing an inference with a declaration. Slightly above the `s` appetite's
upper edge if the residue is large; the triage task is the one to cut scope on (park the residue
under `unassigned` with real reasons now, assign it properly in FEAT-004's review).

---

### Implementation Order

1. **`domains.py` schema + `load_domains`** — dataclasses and the strict parser, developed against a
   hand-written `tests/fixtures/domains/valid.yaml`. Nothing else can be typed until the shape exists.
2. **`dump_domains` + templates + `tests/test_domains.py`** — canonical ordering, round trip,
   uniqueness and template assertions, including `store_ops` → `globalmart-store-ops`.
3. **`traversal.py` extension + `tests/test_traversal.py` additions** — `iter_dashboard_insight_refs`
   as a generic walk, with the nested-layout and drill-target tests. Built before coverage, because
   coverage's correctness is entirely downstream of this.
4. **`tests/fixtures/mini_globalmart/` extension** — the mixed-domain dashboard, the dashboard-less
   visualization, the prefix-less visualization, the memory item. Every later test needs these four
   shapes.
5. **`coverage.py` — classification and `CoverageReport`** — assigned/shared/excluded/uncovered plus
   `unknown_ids`, with `tests/test_coverage.py` written alongside, the predecessor-bug test first.
6. **`coverage.py` — `raise_for_report`, strict mode, and the secondary reports**
   (`multi_homed`, `cross_domain_tiles`, `redundant_visualizations`, `per_domain`).
7. **`domain_bootstrap.py`** — `SEED_DOMAINS`, longest-prefix matching, the ANY rule, TODO parking,
   `BootstrapReport`; `tests/test_domain_bootstrap.py` with the golden file.
8. **`cli.py` — the `domains` group** — `validate` and `bootstrap`, report rendering, exit codes,
   `--force` and `--dry-run` semantics; `tests/test_cli.py` extended.
9. **`tests/test_single_source_of_domains.py`** — written once all source modules exist, so the
   allow-list is final.
10. **Generate the real manifest** — `domains bootstrap --dry-run` against the committed parent tree,
    read the residue, triage with the user, generate, hand-edit the labels/descriptions/reasons.
11. **`tests/test_domains_real.py` + CI job** — the 12/32/384 guard and
    `globalmart domains validate --strict` on every PR.
12. **`docs/domains.md` + ADR 003** — written last, from what the real manifest actually turned out
    to look like.
