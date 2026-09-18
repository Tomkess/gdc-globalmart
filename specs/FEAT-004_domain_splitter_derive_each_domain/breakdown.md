## Technical Breakdown — FEAT-004: Domain splitter: derive each domain workspace from the parent via transitive closure, prune the LDM to reachable datasets, and emit committed declarative JSON per domain

> **Continuity with FEAT-001/002.** No new package, no new console script, no new config file. This extends `src/globalmart/` (console script `globalmart`), reuses `read_tree()` / `write_tree()` from `layout_io.py`, `TargetProfile` / `load_profile()` / `GlobalmartError` from `config.py`, `make_sdk()` from `sdk_client.py`, `count_objects()` / `ObjectCounts` from `counts.py`, `DATASOURCE_ID_TOKEN` / `DATASOURCE_SCHEMA_TOKEN` from `normalize.py`, `iter_datasource_slots()` / `iter_all_string_fields()` from `traversal.py`, `model_digest()` / `model_diff()` from `compare.py`, and — for every write to a live org — `publish_workspace()` from `publish.py` exactly as FEAT-002 defined it. FEAT-004 adds **zero new SDK call sites**.

> **The single invariant this feature exists to enforce.** The predecessor wrote `"ldm": model["ldm"]` into all 12 children, so an "HR workspace" still exposed all 225 retail datasets. Here, a child's LDM is computed by closure and then *verified in both directions* before a byte is written: every reference a retained object makes must resolve inside the pruned LDM (no under-pruning), and every dataset in the pruned LDM must be accounted for — reached by the closure, or named in that domain's `ldm_include`, or a join ancestor of one of those (no over-pruning). Either violation aborts the entire run — all 12 domains, not just the offender.

> **Dependencies are pulled in, never filtered out.** Whether an object travels into a child is decided by reachability from that domain's retained analytics — never by whether its dependencies happened to survive an earlier pass. Once an object is retained, everything it requires (attributes, labels, facts, their datasets, those datasets' join ancestors, date instances, other metrics) is pulled into the closure as a consequence. This is one uniform principle, already visible in the metric closure where `{metric/<id>}` pulls a metric in, and it governs `attributeHierarchies`, `exportDefinitions`, `dashboardPlugins`, `analyticalDashboardExtensions` and `filterContexts` identically. An object nothing retained references is simply not part of that domain: correct absence, not a loss, and never reported as a drop. The only failure is a dependency that *cannot* be satisfied because the referenced object is absent from the parent — a loud, named, non-zero-exit error under the all-or-nothing guarantee.

> **Nothing here assumes the parent.** `publish domains` is a loop over `publish_workspace(sdk, model, profile, workspace_id=..., apply=..., workspace_name=manifest.resolve_workspace_name(domain))`. The generation side never touches a host.

---

### Components

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|
| `src/globalmart/maql.py` | The one place that knows MAQL reference syntax. `MAQL_REF_RE` — a single compiled pattern matching `{<kind>/<id>}` for `kind ∈ {metric, fact, attribute, label, dataset}`, tolerating a granularity suffix (`{label/date_order.month}`) and a quoted id (`{metric/"my id"}`). `iter_maql_refs(maql: str) -> Iterator[MaqlRef]` yields `MaqlRef(kind: RefKind, id: str, granularity: str \| None)`. `RefKind` is a `StrEnum`. No other module may regex MAQL. | New | S |
| `src/globalmart/refs.py` | The one place that knows where object references hide in *non-MAQL* content — the untyped `content` dicts of dashboards, visualization objects and filter contexts, which the SDK models as free-form JSON. Five generators, all operating on `obj.content` as a dict: `iter_dashboard_viz_refs(dashboard)` (every `{"type": "visualizationObject", …}` node, reading `id` or `identifier.id`, covering `section.items[].widget.insight`, `drills[].target`, `drillToInsight`), `iter_dashboard_filter_refs(dashboard)` (filter-context ids and inline `dataSet` / `displayForm` refs), `iter_dashboard_plugin_refs(dashboard)`, `iter_viz_refs(viz)` (every `{"type": "metric"\|"attribute"\|"fact"\|"label"\|"dataset", …}` node inside `buckets[].items[].measure.definition`, `…attribute.displayForm`, `filters[]`, `sorts[]`), `iter_filter_context_refs(fc)` (`attributeFilters[].displayForm`, `dateFilters[].dataSet`). Each yields `ObjectRef(kind: RefKind, id: str, path: str)` — `path` is what an error message quotes. Implemented as a generic recursive walk over the dict looking for `{"type": ..., "id"\|"identifier": ...}` shapes, so a widget variant nobody enumerated is still seen. | New | M |
| `src/globalmart/closure.py` | The expansion engine. `build_closure(model, domain: Domain, manifest) -> DomainClosure` seeds from that domain's dashboards and visualizations **unioned with `manifest.shared.dashboards` / `manifest.shared.visualizations`**, plus `domain.ldm_include` as declared dataset seeds, then runs the six stages under **Data Model** to fixpoint and returns the retained id sets plus a provenance map (`why[object_id] -> list[str]`, the reference chain that pulled it in — this is what makes an error message and the "pulled in solely by dashboard X" report line possible). Pure, host-free, no mutation of `model`. Raises `DanglingReferenceError` the moment a referenced id does not exist in the parent. | New | L |
| `src/globalmart/prune.py` | The LDM pruner. `build_entity_index(ldm) -> EntityIndex` maps every attribute id, label id, fact id, dataset id and date-instance id to its owning dataset id. `expand_join_ancestors(ldm, seed_dataset_ids) -> set[str]` walks `dataset.references[].identifier.id` forward to fixpoint. `prune_ldm(ldm, dataset_ids, date_instance_ids) -> CatalogDeclarativeLdm` returns a new LDM object (deep-copied, never mutating the parent model) holding only those datasets and date instances, with each retained dataset's `references` left intact — the ancestor closure guarantees every target is present. | New | L |
| `src/globalmart/split.py` | Orchestration for one domain and for all of them. `split_domain(model, domain, manifest) -> DomainSplitResult` = closure → prune → assemble a fresh `CatalogDeclarativeWorkspaceModel` → `verify_child()`. `split_all(model, manifest, *, only: set[str] \| None) -> SplitResult` runs every domain, then asserts output coverage against `manifest.unassigned_ids()`, and **collects all failures before raising** so one run names every problem rather than only the first. `assemble_child(...)` is where the five previously-emptied collections are materialized from the closure's retained id sets — they were already decided by reachability in stage 4b, and their dependencies are already in the LDM because that stage fed them into `entity_refs` before stage 5 ran. | New | L |
| `src/globalmart/verify.py` | `verify_child(child_model, domain_key) -> None`, the two-directional gate. **Under-pruning check:** re-walk every retained metric (via `maql.py`), visualization, dashboard and filter context (via `refs.py`) and assert each referenced id resolves inside `child_model` — metric in `analytics.metrics`, entity id in the pruned `EntityIndex`, dataset/date-instance id in the pruned LDM. **Over-pruning check:** assert every dataset id in `child_model.ldm.datasets` is accounted for — a member of the closure's used-or-ancestor set (which now includes datasets pulled in by retained hierarchies, export definitions, plugins and extensions) or of `closure.declared_dataset_ids` or a join ancestor of one of those; a dataset explained by none of these is AC #4's failure. Column-level checks are deliberately absent: a retained dataset's attributes, labels and facts are never pruned, so there is nothing to verify there. Raises `ChildVerificationError` listing `(domain, object_id, reference, reason)` tuples. | New | M |
| `src/globalmart/ai_context.py` | Per-domain filtering of the AI channels, replacing the predecessor's verbatim copy. `filter_ai_context(model, domain, manifest) -> AiContextSelection` keeps the `memoryItems`, parameters, agent personalities and AI-knowledge objects selected by `domain.ai` **unioned with `manifest.shared.ai`** — `memory_item_ids`, `parameter_ids`, `agent_ids`, `knowledge_ids`, plus every memory item whose tags intersect `memory_item_tags` (the rule-based selector FEAT-003 defines, honoured identically here or a tagged item silently misses its child). Every selected id must exist in the parent or `MissingAiContextError` is raised naming it; a `memory_item_tags` entry matching nothing is reported, not fatal. Kept in its own module because FEAT-001 task 31a establishes these as first-class content and the field paths are SDK-version-sensitive. | New | S |
| `src/globalmart/layout_io.py` | Extended with the JSON side of ADR 001, which FEAT-001/002 did not need: `write_model_json(model, path: Path) -> None` — `json.dumps(deep_sort(model.to_api().to_dict(camel_case=True)), sort_keys=True, indent=2, ensure_ascii=False)` plus a trailing newline — and `read_model_json(path) -> CatalogDeclarativeWorkspaceModel`. Also `stable_sort_model(model)` reusing FEAT-001 normalizer pass 5's sort keys, applied before serialization so nested list order is fixed. | Existing — modified | M |
| `src/globalmart/publish.py` | One addition: `publish_domains(sdk, manifest, profile, *, models: dict[str, CatalogDeclarativeWorkspaceModel], only, apply, no_backup, standalone_copy) -> list[PublishResult]`, a loop calling the **unchanged** `publish_workspace()` once per domain with `workspace_id=resolved_workspace_id(profile, domain.workspace_id)` and `workspace_name=manifest.resolve_workspace_name(domain)` — the manifest renders the name (override else `workspace_name_template`), this module never concatenates it. Aggregates results; on a per-child failure it records and continues under `--apply` only if `--keep-going` is passed, otherwise stops at the first failure with the remaining domains listed as not attempted. | Existing — modified | S |
| `src/globalmart/cli.py` | Two subcommands. `globalmart split [--domains-file config/domains.yaml] [--from layouts/workspaces/globalmart] [--out generated/workspaces] [--only sales,hr] [--dry-run] [--check]` — writes **local files**, so per ADR 002 it takes `--dry-run` (report only, write nothing) and `--check` (exit 1 if any emitted file would differ from what is committed; the CI gate). `globalmart publish domains --target <profile> [--in generated/workspaces] [--only …] [--apply] [--no-backup] [--standalone-copy] [--keep-going]` — writes to a **live org**, so it takes `--apply` and has no `--dry-run`, sitting beside `publish parent` in the group FEAT-002 shaped. | Existing — modified | M |
| `domains.yaml` | Consumed, not defined — FEAT-003 owns it. The reconciled contract is pinned under **Data Model**. | External to this feature | — |
| `generated/workspaces/globalmart-<domain>.json` | The 12 committed, reviewable artifacts. | New (generated, committed) | — |
| `tests/fixtures/mini_domains/` | A committed mini parent (`mini_parent/` YAML tree) plus `domains.yaml` designed so the assertions are hand-checkable: 3 domains, 9 datasets (2 shared dimensions, 1 date instance used by only one domain, a 3-hop join chain `fact_orders → dim_customer → dim_geo`, 1 SQL-backed dataset), 12 metrics (one with a 3-deep `{metric/…}` chain, one referencing a `{label/…}` on a dataset no visualization touches), 6 visualizations, 3 dashboards (one deliberately mixed-domain), 1 attribute hierarchy spanning two domains, 2 export definitions, 1 dashboard plugin, memory items and parameters split across domains, a `shared:` block carrying one dashboard, one visualization and one `shared.ai` parameter so the belongs-in-every-child rule is exercised by construction, an `ldm_include` on one domain naming a dataset that domain's analytics do not reach (so the declared-widening path is exercised too), and — for the hierarchy pull-in — one of the spanning hierarchy's attributes living on a dataset no visualization in either domain touches, so a filter-out design would drop the hierarchy while the pull-in design retains it and brings that dataset in. | New | L |
| `tests/fixtures/expected_children/` | The three hand-computed expected child JSONs for `mini_domains`, committed, with a test asserting regeneration is byte-identical. | New | M |
| `tests/` (7 new modules, see Test Strategy) | `test_maql.py`, `test_refs.py`, `test_closure.py`, `test_prune.py`, `test_verify.py`, `test_split.py`, `test_publish_domains.py`; plus extensions to `test_layout_io.py`, `test_cli.py`, `test_no_hardcoded_identifiers.py`. | New | L |
| `docs/domain-split.md` | One page: the closure stages in order, the prune rules, what "fails loudly" means, how to read the split report, and the explicit statement that a generated file is never hand-edited. | New | S |
| CI | `globalmart split --check` added beside FEAT-001's `normalize --check`. | Existing — modified | S |

---

### Data Model

#### The FEAT-003 contract this feature consumes (reconciled — FEAT-003 owns and defines it)

```python
# src/globalmart/domains.py — OWNED BY FEAT-003, reproduced here as the consumed contract
@dataclass(frozen=True)
class AiSelection:
    memory_item_ids: tuple[str, ...]
    memory_item_tags: tuple[str, ...]     # RULE, not ids: a memory item carrying any listed tag is in
    parameter_ids: tuple[str, ...]
    agent_ids: tuple[str, ...]
    knowledge_ids: tuple[str, ...]

@dataclass(frozen=True)
class Domain:
    key: str                              # snake_case, e.g. "store_ops"
    label: str                            # human label, e.g. "Store Operations" — NOT the published name
    description: str
    workspace_id: str                     # "globalmart-store-ops" (key underscores -> hyphens)
    workspace_name: str | None            # per-domain override of the rendered name template
    dashboards: tuple[str, ...]           # explicit analyticalDashboard ids
    visualizations: tuple[str, ...]       # extra visualizationObject ids not reachable from them
    ai: AiSelection                       # NESTED — there are no flat ai id fields on Domain
    ldm_include: tuple[str, ...]          # dataset ids this child's LDM gets BEYOND closure reach,
                                          # so new metrics/visualizations can be authored in it.
                                          # LDM only: never coverage, and not the shared: block.

@dataclass(frozen=True)
class Exclusion:
    id: str
    reason: str

@dataclass(frozen=True)
class SharedSelection:                    # belongs in EVERY child
    dashboards: tuple[str, ...]
    visualizations: tuple[str, ...]
    ai: AiSelection

@dataclass(frozen=True)
class UnassignedSelection:                # deliberate, reasoned exclusions
    dashboards: tuple[Exclusion, ...]
    visualizations: tuple[Exclusion, ...]
    ai: tuple[Exclusion, ...]

@dataclass(frozen=True)
class DomainManifest:
    version: int
    parent_workspace_id: str              # "globalmart"
    workspace_id_template: str            # default "globalmart-{key_kebab}"
    workspace_name_template: str          # default "GlobalMart — {label}"
    domains: tuple[Domain, ...]           # ordered by key, 12 today
    shared: SharedSelection
    unassigned: UnassignedSelection
    path: Path
    def by_key(self, key: str) -> Domain: ...
    def keys(self) -> tuple[str, ...]: ...
    def resolve_workspace_name(self, domain: Domain) -> str: ...   # override else template
    def unassigned_ids(self) -> frozenset[str]: ...                # flattened exclusion ids

def load_domains(path: Path) -> DomainManifest: ...
class DomainManifestError(GlobalmartError): ...
```

Four properties of this contract shape everything below, and FEAT-004 must not work around any of them:

1. **`shared` is not optional surface.** Its `dashboards` and `visualizations` belong in *every* child, so every domain's closure seeds from `domain.dashboards | manifest.shared.dashboards` and `domain.visualizations | manifest.shared.visualizations`, and every child's AI filter unions `domain.ai` with `manifest.shared.ai`. Treating `shared` as absent would silently drop those objects from all 12 children — the exact class of silent drop this feature exists to eliminate.
2. **AI selection is nested and partly rule-based.** Read `domain.ai.memory_item_ids`, `domain.ai.parameter_ids`, `domain.ai.agent_ids`, `domain.ai.knowledge_ids`, and honour `domain.ai.memory_item_tags` — a memory item carrying any listed tag is included in that domain, as it is in FEAT-003's own coverage check. There are no flat AI fields on `Domain`.
3. **The published name comes from the manifest, never from string concatenation.** `manifest.resolve_workspace_name(domain)` is the only producer of the `workspace_name` passed to `publish_workspace()`; `domain.label` is the bare human label (`Sales`), not the published name (`GlobalMart — Sales`). Likewise the unassigned allow-list is `UnassignedSelection` of `Exclusion(id, reason)`, read through `manifest.unassigned_ids()` when only membership is needed.
4. **`ldm_include` is authoring headroom, expressed at dataset granularity.** A child pruned to exactly what today's dashboards touch is correct but sterile — a new metric cannot be authored on a table closure never reached. `domain.ldm_include` names datasets to add to the closure seed; their join ancestors are pulled in exactly as any other retained dataset's. A declared id absent from the parent fails the run. It affects **only** the LDM: it never covers a dashboard, visualization or AI object, and it is not `shared:` (which declares analytics belonging in every child). The report keeps the two sources apart — `hr: 18 datasets (14 by closure, 4 declared)` — so declared widening stays visible.

FEAT-004 assumes `load_domains()` has already validated shape, uniqueness and *input* coverage. It re-asserts *output* coverage itself (AC #9), because a manifest can be valid while the closure still leaves an object unreached.

#### New types

**`RefKind`** (`maql.py`, `StrEnum`): `METRIC`, `FACT`, `ATTRIBUTE`, `LABEL`, `DATASET`, `DATE_INSTANCE`.

**`MaqlRef`** (`maql.py`, `NamedTuple`): `kind: RefKind`, `id: str`, `granularity: str | None`.

**`MAQL_REF_RE`** — one pattern, one owner:

```python
MAQL_REF_RE = re.compile(
    r"\{(metric|fact|attribute|label|dataset)/"       # kind
    r'(?:"(?P<quoted>[^"]+)"|(?P<bare>[^}./]+))'      # id, quoted or bare
    r"(?:\.(?P<granularity>[^}]+))?\}"                # optional .month / .year
)
```

**`ObjectRef`** (`refs.py`, `NamedTuple`): `kind: RefKind`, `id: str`, `path: str` (e.g. `content.sections[0].items[2].widget.insight`).

**`EntityIndex`** (`prune.py`, frozen dataclass) — built once per split run from `model.ldm`:

| Field | Type | Built from |
|---|---|---|
| `attribute_to_dataset` | `dict[str, str]` | `dataset.attributes[].id` |
| `label_to_dataset` | `dict[str, str]` | `dataset.attributes[].labels[].id` (and `defaultView`) |
| `fact_to_dataset` | `dict[str, str]` | `dataset.facts[].id` + `dataset.aggregated_facts[].id` |
| `dataset_ids` | `frozenset[str]` | `ldm.datasets[].id` |
| `date_instance_ids` | `frozenset[str]` | `ldm.date_instances[].id` |
| `references` | `dict[str, tuple[str, ...]]` | `dataset.references[].identifier.id` — the join edges |
| `grain` | `dict[str, tuple[str, ...]]` | `dataset.grain[].id` with its `type` |

`resolve_entity(ref: MaqlRef \| ObjectRef) -> str` returns the owning dataset id, or raises `DanglingReferenceError` naming the ref. A `LABEL`/`ATTRIBUTE` whose id matches a `date_instance_id` (or whose id is `<date_instance>.<granularity>`) resolves to that date instance, not to a dataset.

**`DomainClosure`** (`closure.py`, frozen dataclass) — the output of the six stages:

| Field | Type | Meaning |
|---|---|---|
| `domain_key` | `str` | |
| `dashboard_ids` | `frozenset[str]` | seed, verbatim from the manifest |
| `visualization_ids` | `frozenset[str]` | seed extras + everything reachable from the dashboards |
| `metric_ids` | `frozenset[str]` | after transitive MAQL closure |
| `filter_context_ids` | `frozenset[str]` | referenced by retained dashboards |
| `attribute_hierarchy_ids` | `frozenset[str]` | referenced by a retained visualization, dashboard or drill definition (stage 4b) |
| `export_definition_ids` | `frozenset[str]` | whose target visualization/dashboard is retained (stage 4b) |
| `dashboard_plugin_ids` | `frozenset[str]` | referenced by a retained dashboard (stage 4b) |
| `dashboard_extension_ids` | `frozenset[str]` | whose dashboard is retained (stage 4b) |
| `entity_refs` | `frozenset[tuple[RefKind, str]]` | every LDM entity touched by **any** retained object, auxiliary ones included |
| `seed_dataset_ids` | `frozenset[str]` | datasets owning those entities — **before** ancestor expansion |
| `declared_dataset_ids` | `frozenset[str]` | `domain.ldm_include`, validated against the parent; seeded alongside `seed_dataset_ids` and reported separately so declared widening stays visible |
| `dataset_ids` | `frozenset[str]` | after `expand_join_ancestors` over `seed_dataset_ids \| declared_dataset_ids` |
| `date_instance_ids` | `frozenset[str]` | |
| `why` | `dict[str, tuple[str, ...]]` | provenance chain per retained id, for errors and the report |

#### The closure algorithm — six stages, run in order, each to fixpoint

Every stage obeys the same rule: reachability decides what is retained, and whatever is retained feeds its own references back into the closure, so its dependencies are pulled in rather than required to have survived independently.

1. **Seed.** `dashboard_ids = set(domain.dashboards) | set(manifest.shared.dashboards)`; `visualization_ids = set(domain.visualizations) | set(manifest.shared.visualizations)`; `declared_dataset_ids = set(domain.ldm_include)`. The `shared` union is part of the seed, not an afterthought: a shared dashboard belongs in *every* child, and seeding it here means stages 2–5 pull its visualizations, metrics and datasets into every child too. Every seed id must exist in the parent (`analytics.analytical_dashboards` / `analytics.visualization_objects`, and `ldm.datasets` for the declared ones) or raise `DanglingReferenceError`. `why` records a shared-seeded id as coming from `shared` and a declared dataset as coming from `ldm_include`, so the report distinguishes both from a domain's own membership.
2. **Dashboards → visualizations, filter contexts, plugins.** For each retained dashboard, `iter_dashboard_viz_refs` adds visualization ids (including drill targets — a drill-to-insight target that is missing is exactly the kind of runtime break this stage prevents); `iter_dashboard_filter_refs` adds `filter_context_ids` and any inline `displayForm` / `dataSet` refs straight into `entity_refs`; `iter_dashboard_plugin_refs` records plugin ids. Drill targets can themselves be dashboards, so this stage loops until `dashboard_ids` and `visualization_ids` stop growing.
3. **Visualizations → metrics and entities.** For each retained visualization, `iter_viz_refs` classifies each node: `METRIC` → `metric_ids`; `ATTRIBUTE` / `LABEL` / `FACT` / `DATASET` → `entity_refs`. Buckets carry `measure.definition.measure.item` (a metric), `measure.definition.inline.maql` (raw MAQL — fed through `maql.iter_maql_refs`), `attribute.displayForm` (a label), and `filters[].*.displayForm` / `dateFilter.dataSet`.
4. **Metric transitive closure — the part kept verbatim from the predecessor.** Worklist over `metric_ids`; for each metric, `iter_maql_refs(metric.content["maql"])`; `METRIC` refs are appended to the worklist (fixpoint — a metric referencing a metric referencing a metric all travel), everything else lands in `entity_refs`. This is the logic whose absence produced `"metrics … cannot be found"`, and it is why the closure is a worklist rather than a two-pass walk.

4b. **Reachable auxiliary objects — hierarchies, export definitions, plugins, extensions, filter contexts.** Retention is decided here, *before* datasets are resolved, which is what makes the pull-in rule work. An `attributeHierarchy` is retained iff a retained visualization, dashboard or drill definition references it; an `exportDefinition` iff its `requestPayload` target visualization/dashboard is retained; a `dashboardPlugin` iff a retained dashboard references it; an `analyticalDashboardExtension` iff its dashboard is retained; a `filterContext` iff a retained dashboard references it (stage 2 already collects these). Each retained object's own references are then fed into `entity_refs` and, for metrics, back onto stage 4's worklist — so a hierarchy's attributes, their datasets and those datasets' join ancestors are **pulled into** the closure by stage 5 as a consequence of the hierarchy travelling. No auxiliary object is ever excluded because a referent was not already retained; the referent is included instead. An object no retained object references is not part of this domain — correct absence, recorded nowhere as a loss. A reference to an object absent from the *parent* raises `DanglingReferenceError`, which is the one and only failure mode here. Stages 2–4 and 4b loop together until nothing grows, since a retained export definition can name a dashboard that in turn pulls new visualizations and metrics in.

5. **Entities → datasets → join ancestors → date instances.** `seed_dataset_ids = {index.resolve_entity(r) for r in entity_refs}` minus anything resolving to a date instance, which goes to `date_instance_ids`; `entity_refs` at this point includes everything stage 4b's retained objects contributed. Then `dataset_ids = expand_join_ancestors(ldm, seed_dataset_ids | declared_dataset_ids)`: worklist over `index.references[d]`, following each edge **forward only** — `dataset.references` points from a dataset to the datasets it joins *to* (its dimensions / ancestors), so a retained fact table drags its dimensions in, while a retained dimension never drags in the facts that point at it. That asymmetry is exactly the narrowing the feature wants. Any `references` edge whose target is a date instance id adds that date instance. Finally each retained dataset's `grain` entries are resolved the same way; a grain entry pointing at a date dataset adds that date instance.

#### The prune algorithm

`prune_ldm(ldm, dataset_ids, date_instance_ids)`:

1. `deepcopy` the LDM — the parent model is never mutated, so `split_all` can run all 12 domains from one loaded tree.
2. Keep `datasets` where `id in dataset_ids`, sorted by `id`.
3. Keep `date_instances` where `id in date_instance_ids`, sorted by `id`.
4. Leave each retained dataset's `attributes`, `labels`, `facts`, `grain` and `references` **intact**. Dataset-level pruning only, decided and closed (spec § Out of Scope): a retained dataset keeps every column it has, because a label that looks unused may be a join grain or another dataset's `reference` target — stripping it breaks the child only at execution time — and because those columns are the headroom a child needs to author new analytics. `references` need no filtering because stage 5 guaranteed every target is retained; `verify_child` asserts this rather than trusting it. The split report records per-dataset used/total attribute and fact counts, so a future column-pruning proposal can be argued from measurement.
5. Leave `data_source_id` as `{{ datasource_id }}` and SQL statements as `{{ datasource_schema }}` — resolution is FEAT-002's job at publish time (AC #12).

#### `assemble_child` — what goes into the emitted model

| Child field | Source | Rule |
|---|---|---|
| `ldm.datasets`, `ldm.date_instances` | `prune_ldm` | closure-reachable (including everything pulled in by retained hierarchies, export definitions, plugins and extensions) plus `domain.ldm_include`, plus the join ancestors of both; each retained dataset keeps all its columns |
| `analytics.metrics` | parent | `id in closure.metric_ids` |
| `analytics.visualization_objects` | parent | `id in closure.visualization_ids` |
| `analytics.analytical_dashboards` | parent | `id in closure.dashboard_ids` |
| `analytics.filter_contexts` | parent | `id in closure.filter_context_ids` |
| `analytics.attribute_hierarchies` | parent | `id in closure.attribute_hierarchy_ids` — decided in stage 4b by reachability from a retained visualization, dashboard or drill definition. Retention already pulled its attributes, their datasets and those datasets' join ancestors into the LDM, so it is never excluded for referencing something an earlier pass omitted (predecessor hardcoded `[]`) |
| `analytics.export_definitions` | parent | `id in closure.export_definition_ids` — retained iff its `requestPayload` target visualization/dashboard is retained, with its dependencies pulled in by stage 4b (predecessor hardcoded `[]`) |
| `analytics.dashboard_plugins` | parent | `id in closure.dashboard_plugin_ids` — retained iff referenced by a retained dashboard (predecessor hardcoded `[]`) |
| `analytics.analytical_dashboard_extensions` | parent | `id in closure.dashboard_extension_ids` — retained iff its dashboard is retained (predecessor hardcoded `[]`) |
| AI context (`memoryItems`, parameters, agents, knowledge) | `ai_context.filter_ai_context` | `domain.ai` ∪ `manifest.shared.ai`, ids plus `memory_item_tags` matches; cross-domain leak is a defect, and a `shared.ai` item missing from a child is equally a defect |

`assemble_child` decides nothing on its own: every row above is a lookup into a closure id set that stages 2–4b already settled. There is consequently no "dropped because its referents were pruned" case to record — an object either travels (and its dependencies came with it), or nothing in the domain reaches it and it is correctly absent, or a dependency is missing from the parent and the whole run fails loudly. The report therefore names what each child *retained* and, for correct absences, stays quiet.

**`DomainSplitResult`** (`split.py`, dataclass) — one per domain, printed and asserted:

| Field | Type |
|---|---|
| `domain_key` | `str` |
| `workspace_id` | `str` |
| `label` | `str` (the bare human label from the manifest) |
| `workspace_name` | `str` (from `manifest.resolve_workspace_name(domain)` — the published display name, never built by concatenation here) |
| `counts` | `ObjectCounts` (FEAT-001's, reused) |
| `datasets_retained` | `int` |
| `datasets_by_closure` | `int` (reached by the closure, auxiliary-object pull-ins included) |
| `datasets_declared` | `int` (from `domain.ldm_include`, not otherwise reached — the report prints the pair as `hr: 18 datasets (14 by closure, 4 declared)`) |
| `datasets_pruned` | `int` (225 − retained) |
| `datasets_from_ancestors_only` | `int` (in `dataset_ids` but in neither `seed_dataset_ids` nor `declared_dataset_ids`) |
| `dataset_column_usage` | `dict[str, tuple[int, int, int, int]]` (per retained dataset: used/total attributes, used/total facts — all columns are kept, so this is evidence for a future column-pruning decision, not a pruning input) |
| `date_instances_retained` | `int` |
| `metrics_from_maql_closure` | `int` (retained metrics not directly referenced by any retained visualization) |
| `hierarchies_retained` / `export_definitions_retained` / `plugins_retained` / `extensions_retained` | `list[str]` (what travelled; there is no `dropped_*` counterpart — an object nothing in the domain references is correctly absent, not a loss, and an unsatisfiable dependency is an error, not a report line) |
| `ai_context_ids` | `frozenset[str]` |
| `digest` | `str` (`compare.model_digest`) |
| `path` | `Path` |

**`SplitResult`** (`split.py`): `domains: list[DomainSplitResult]`, `unassigned_ids: frozenset[str]` (from `manifest.unassigned_ids()` — the flattened `Exclusion` ids, reasons stay on `manifest.unassigned`), `shared_ids: frozenset[str]` (what every child carries from the `shared` block), `coverage_ok: bool`, `failures: list[str]`.

**Exceptions** (all subclasses of FEAT-002's `GlobalmartError`): `DanglingReferenceError` (`closure.py`), `ChildVerificationError` (`verify.py`), `MissingAiContextError` (`ai_context.py`), `CoverageError` (`split.py`).

#### Determinism

Emission order is fixed at three levels: (1) `stable_sort_model()` applies FEAT-001 pass-5 sort keys to every list; (2) `deep_sort` + `json.dumps(sort_keys=True, indent=2, ensure_ascii=False)` fixes mapping order; (3) domains are processed in `manifest.keys()` order, which `load_domains` sorts. `set` iteration never reaches output — every set is converted to a sorted list before serialization. This is what makes `git diff generated/workspaces/` the review surface (ADR 001) and what `--check` enforces.

---

### Integration Points

- **FEAT-003 `domains.yaml` / `load_domains()`** — the reconciled contract is pinned under **Data Model**. FEAT-004 calls `load_domains(Path("config/domains.yaml"))` and nothing else; it never parses the YAML itself and never re-implements validation. It reaches the manifest only through `by_key()`, `keys()`, `resolve_workspace_name()`, `unassigned_ids()`, `manifest.shared`, `domain.ai` and `domain.ldm_include` — it does not render the name template, flatten the exclusion lists, or assume flat AI fields on `Domain`. `domain.ldm_include` is consumed as a closure seed and reported separately; FEAT-003 owns its schema and its existence validation.
- **FEAT-001** — `read_tree()` for the parent; `layout_io.py` extended with `write_model_json` / `read_model_json` / `stable_sort_model`; `count_objects()` / `ObjectCounts` reused per child; `DATASOURCE_ID_TOKEN` / `DATASOURCE_SCHEMA_TOKEN` imported, never re-declared. Normalizer pass 5's sort keys are lifted into `stable_sort_model()` so YAML and JSON emission cannot drift.
- **FEAT-002** — `publish_workspace(sdk, model, profile, *, workspace_id, apply=False, standalone_copy=False)` is called unchanged, once per child, with `workspace_name=manifest.resolve_workspace_name(domain)` (the `--workspace-name` parameter FEAT-002 already exposes, fed by FEAT-003's template so the two features cannot disagree about the published name) and `workspace_id=resolved_workspace_id(profile, domain.workspace_id)` so `workspace_id_prefix` applies to children exactly as to the parent. `resolve.py` performs all placeholder substitution at publish time; `compare.py` supplies `model_digest` for the split report and the idempotency assertion; `preflight`, `backup` and the `--apply` gate come along for free with each call.
- **`gooddata-python-sdk`** — model classes only on the generation side (`CatalogDeclarativeWorkspaceModel`, `CatalogDeclarativeLdm`, `CatalogDeclarativeDataset`, `deep_sort`, `to_api().to_dict(camel_case=True)`). **No new SDK call site.** Dashboard, visualization and filter-context `content` is free-form JSON in the SDK model, which is why `refs.py` exists and why it walks generically rather than against typed attributes.
- **Git** — `generated/workspaces/*.json` are committed artifacts under review (ADR 001). `.gitattributes` extended with `generated/**/*.json text eol=lf`.
- **CI** — `globalmart split --check` runs beside FEAT-001's `normalize --check`; a hand-edited generated file or a parent change not re-split fails the build. No CI job publishes to a live org (STEERING § AI Behavior).
- **FEAT-006** — consumes the 12 published children and each `DomainSplitResult.counts` / `digest` for the cold-rebuild smoke test.

---

### Test Strategy

Everything runs offline against `tests/fixtures/mini_domains/` (a 3-domain mini parent) plus the real committed parent tree where a corpus-wide assertion is cheap. `uv run pytest tests/ -x -q`. The `FakeSdk` from FEAT-002's `tests/conftest.py` is reused unchanged for the publish tests.

**Unit — `tests/test_maql.py`**
- `iter_maql_refs` extracts all five kinds; a granularity suffix (`{label/date_order.month}`) yields `id="date_order"`, `granularity="month"`; a quoted id yields the unquoted id; a MAQL string with no refs yields nothing; nested braces inside a `WHERE` clause do not produce a phantom ref.
- **Corpus test against the real parent:** run `iter_maql_refs` over all 1075 metrics in `layouts/workspaces/globalmart/` and assert every extracted id resolves to a real metric, attribute, label, fact or dataset. An unresolvable extraction means the regex is wrong or the parent is broken, and both must fail (the spec's fourth risk row, mechanized). Skipped cleanly until the real tree exists.

**Unit — `tests/test_refs.py`**
- `iter_dashboard_viz_refs` finds a visualization referenced from a section widget, from a drill target, and from a `drillToInsight` — three shapes, one walk.
- The generic walk finds a `{"type": "metric", "id": …}` node nested at a depth no enumerator names (defence against widget-schema drift).
- `iter_viz_refs` classifies a metric, a label via `attribute.displayForm`, a fact inside an inline-MAQL measure, and a date filter's `dataSet`, each with a `path` that names where it was found.

**Unit — `tests/test_closure.py`**
- Stage 2: the mixed-domain dashboard in the fixture pulls visualizations from both domains — and, unlike the predecessor's prefix rule, is **not** silently dropped; the split succeeds and the report names the cross-domain pull.
- Stage 4 (the kept-verbatim part): the 3-deep `{metric/…}` chain is fully retained; removing the transitive step from the closure makes the test fail with the same "cannot be found" shape the predecessor produced.
- **Shared seeding:** the fixture's `shared.dashboards` / `shared.visualizations` entries are in the closure of **all three** domains, and `why` attributes them to `shared` rather than to a domain's own list. The negative form — building the closure from `domain.dashboards` alone — leaves them out of two children, which is the silent drop this assertion exists to catch.
- **Stage 4b — the pull-in rule:** the fixture's spanning attribute hierarchy is retained in every domain whose retained analytics reference it, and the dataset owning the attribute that no visualization in that domain touches is in `dataset_ids` **because** the hierarchy travelled — `why` names the hierarchy as the reason. The negative form, deciding hierarchy retention after the LDM is pruned, leaves that hierarchy out of both children; that is the design this test exists to prevent. The same assertion runs for an export definition whose target pulls in a dataset analytics alone would not reach.
- **Stage 1 — `ldm_include`:** a declared dataset is in `declared_dataset_ids` and in `dataset_ids` with its join ancestors, `why` attributes it to `ldm_include`, and it is absent from `seed_dataset_ids`; a declared id absent from `ldm.datasets` raises `DanglingReferenceError` naming domain and id.
- `DanglingReferenceError` on a manifest naming a dashboard id that does not exist in the parent, naming the domain and the id.
- `why` provenance: the chain recorded for a transitively-pulled metric names the dashboard and the visualization it came through.

**Unit — `tests/test_prune.py`**
- `build_entity_index` maps a nested label to its dataset and a date-instance-qualified label to the date instance rather than to a dataset.
- **Join direction (the spec's third risk):** on the fixture's `fact_orders → dim_customer → dim_geo` chain, seeding `{fact_orders}` retains all three; seeding `{dim_geo}` retains only `dim_geo`. Hand-computed expected sets, asserted literally.
- A dataset reachable only as a join ancestor is retained and is counted in `datasets_from_ancestors_only`.
- `prune_ldm` does not mutate the input LDM — the parent model is re-usable for the next domain (asserted by digesting the parent before and after all three domains are split).

**Unit — `tests/test_verify.py`** — the two gates, both directions
- **Under-pruning:** hand-build a child whose retained metric MAQL references `{label/…}` on a dataset removed from the LDM; `verify_child` must raise `ChildVerificationError` naming the domain, the metric id and the label ref. This is AC #8.
- **Over-pruning — the defect-#2 regression test:** take a correctly generated child, inject one extra dataset into its `ldm.datasets` that no retained object references and that the domain does not declare in `ldm_include`, and assert `verify_child` raises naming that dataset. The complements are asserted alongside, so the gate cannot be read as "unreferenced by analytics ⇒ unused": a dataset present solely because a retained attribute hierarchy or export definition needed it passes, and so does one present solely because `ldm_include` declared it. A test that also runs the degenerate form — a child carrying the *full* 225-dataset parent LDM — and asserts it fails, which is precisely what the predecessor shipped 12 times.
- A retained dataset whose `references` target is absent raises, rather than emitting a dangling join.

**Integration (offline) — `tests/test_split.py`**
- `split_all` on `mini_domains` produces exactly 3 children matching `tests/fixtures/expected_children/` **byte for byte**; re-running produces identical bytes (AC #2 without git).
- Per-domain `datasets_retained` equals the hand-computed number and is strictly less than the fixture's total — the narrowing assertion, regression-pinned so an over-broad closure change fails CI.
- **The previously-hardcoded collections, under the pull-in rule.** The fixture's attribute hierarchy spans two domains: it lands in **every** child whose retained analytics reference it, and in each such child the datasets of *all* its attributes — including any the analytics closure alone would not have reached — are present in the pruned LDM. It is never dropped from a child for naming an attribute that closure missed. A child that references it nowhere simply does not have it, and that absence is asserted as correct, not reported as a loss; there is no `dropped_*` list to assert against. The 2 export definitions and the dashboard plugin are asserted the same way, each landing in the child whose retained objects reference it and pulling its own dependencies in. The unsatisfiable case is separate: a fixture hierarchy naming an attribute that exists in **no** parent dataset makes the whole run exit non-zero naming the hierarchy and the attribute, and leaves the output directory empty.
- **`ldm_include` (AC #18):** the fixture manifest's declared dataset appears in that child's `ldm.datasets` with its join ancestors and with all of its attributes, labels and facts; `datasets_declared` counts it while `datasets_by_closure` does not, and the report line shows the pair; `verify_child` accepts it rather than flagging it as unused; the other two children, which declare nothing, do not have it; and a declared id absent from the parent fails the run naming the domain and the id.
- AI context: the pairwise intersection of the three children's `ai_context_ids` is exactly the `shared.ai` id set — domain-selected items never cross, shared items always do; a memory item carried into a domain only by a `memory_item_tags` match is present in that child and absent from the others; a domain selecting a memory-item id absent from the parent raises `MissingAiContextError` naming it.
- **Shared objects reach every child (AC #17):** every id in the manifest's `shared` block — its dashboards, its visualizations and its `shared.ai` selections — appears in all three generated children, and the pruned LDM of each child retains the datasets those shared objects need. Removing the `shared` union from the seed or from the AI filter makes this test fail in two of the three children, which is precisely the silent drop the feature exists to eliminate.
- Coverage (AC #9): removing a dashboard from the manifest without adding it to `unassigned` fails with `CoverageError` naming the dashboard; adding it as an `Exclusion(id, reason)` under `unassigned.dashboards` — reached through `manifest.unassigned_ids()` — passes.
- **All-or-nothing:** a fixture where domain 2 of 3 fails verification leaves `tmp_out/` empty — domain 1's file is not written either.
- Placeholders survive (AC #12): every generated child's `dataSourceId` is `{{ datasource_id }}` and its SQL statements contain `{{ datasource_schema }}`; a grep of the generated JSON for `globalmart-motherduck` returns zero hits.

**Integration (offline) — `tests/test_publish_domains.py`**
- Against `FakeSdk` with `apply=True`: exactly one `put_declarative_workspace` per domain, with `workspace_id` = `globalmart-<domain>` after `resolved_workspace_id` (including under a non-empty `workspace_id_prefix`) and the `CatalogWorkspace` name equal to `manifest.resolve_workspace_name(domain)` — `GlobalMart — Sales` for `label: Sales` under the default template, and the per-domain `workspace_name` override where the fixture sets one. Asserted against the manifest helper, never against a string this test builds itself.
- Without `--apply`: zero write calls across all domains, diffs still produced for each (ADR 002, per child).
- Idempotency: publish twice against a `FakeSdk` that serves back what it was given; all `PublishResult.changed` are `False` on the second pass.
- `--only sales,hr` publishes exactly two workspaces and touches no other.
- A per-child failure stops the loop and the report lists the domains not attempted; with `--keep-going` it continues and the exit code is still non-zero.

**Extensions to existing modules**
- `tests/test_layout_io.py`: `write_model_json` is byte-stable across two writes; `read_model_json(write_model_json(m))` round-trips equal under `to_api().to_dict(camel_case=True)`.
- `tests/test_cli.py`: `split --dry-run` writes no file and prints the report; `split --check` exits 0 on committed output and 1 on a hand-edited file naming it; `publish domains` rejects `--no-backup` without `--apply` exactly as `publish parent` does.
- `tests/test_no_hardcoded_identifiers.py`: extend the forbidden-string list with the 12 domain keys and `globalmart-<domain>` (AC #15) — the predecessor had the domain list in four places.

**Manual, once, user-initiated (per STEERING § AI Behavior)**
- Run `globalmart split` on the real parent; read the report and sanity-check the 12 `datasets_retained` figures (an HR child in the tens, not 225); `git diff` the 12 generated files as the review artifact; re-run and confirm `git status` is clean.
- Then `globalmart publish domains --target demo-cloud` (rehearsal), then `--apply`, then a third `--apply` run confirming `changed is False` for all 12.

---

### Total Effort Estimate

| Scale | Meaning |
|---|---|
| S | A few hours |
| M | 1–3 days |
| L | 1–2 weeks |
| XL | More than a sprint — consider splitting the feature |

| Area | Effort |
|---|---|
| `maql.py` + `refs.py` (reference extraction) | M |
| `closure.py` (six stages, provenance) | L |
| `prune.py` (entity index, join-ancestor fixpoint) | L |
| `verify.py` (both-direction gates) | M |
| `split.py` + `ai_context.py` (assembly, filtering, coverage) | L |
| `layout_io.py` JSON side + determinism | M |
| `publish.py` / `cli.py` wiring | M |
| `tests/fixtures/mini_domains/` + `expected_children/` | L |
| Test suite (7 new modules + 3 extensions) | L |
| Real run, review of 12 diffs, docs | M |

**Overall: L (2–3 weeks).** The SDK gives nothing here — closure, pruning and verification are all ours, and the two genuinely hard parts are (a) enumerating every place a reference can hide in the untyped `content` dicts of 384 visualizations and 32 dashboards, which is why `refs.py` walks generically instead of against a schema, and (b) building `tests/fixtures/mini_domains/` small enough that the expected retained-dataset sets can be computed by hand yet wide enough to cover a 3-hop join chain, a mixed-domain dashboard, a 3-deep metric chain, a date instance used by one domain only, and a spanning attribute hierarchy. Getting the join direction and the fixpoint right is a day; proving it is a week. Matches the `l` appetite.

---

### Implementation Order

1. **`maql.py`** — `MAQL_REF_RE`, `RefKind`, `MaqlRef`, `iter_maql_refs`, plus `tests/test_maql.py` including the 1075-metric corpus assertion. Everything downstream depends on reference extraction being right, and this is the cheapest place to prove it.
2. **`refs.py`** — the generic `content`-dict walk and the five typed generators, with `tests/test_refs.py`. Pure, fixture-free at first (hand-written dicts), then against the mini parent.
3. **`tests/fixtures/mini_domains/`** — the mini parent tree plus its `domains.yaml`, built by trimming FEAT-001's `mini_globalmart` and adding the shapes listed above. Built here because steps 4–7 cannot be tested without it.
4. **`prune.py` part 1 — `EntityIndex`** — the entity→dataset map and `resolve_entity`, with the date-instance special case. Tested before any closure exists.
5. **`prune.py` part 2 — `expand_join_ancestors` + `prune_ldm`** — the join fixpoint and the deep-copied pruned LDM, with the direction test on the 3-hop chain. This is the feature's centre of gravity.
6. **`closure.py`** — the six stages in order, stage 4 lifted from the predecessor and made a worklist, stage 4b deciding the auxiliary objects by reachability and feeding their references back in so stage 5 pulls their datasets, `ldm_include` seeded in stage 1, `why` provenance throughout, `DanglingReferenceError`. `tests/test_closure.py` alongside.
7. **`verify.py`** — both gates, written *before* `split.py` so no child can ever be assembled without them. `tests/test_verify.py` includes the defect-#2 regression test.
8. **`ai_context.py`** — per-domain AI-channel filtering and `MissingAiContextError`.
9. **`layout_io.py` extension** — `stable_sort_model`, `write_model_json`, `read_model_json`, `.gitattributes`; `tests/test_layout_io.py` extended. Needed before anything is emitted.
10. **`split.py`** — `assemble_child` (materializing the five no-longer-emptied collections from the closure's id sets), `split_domain`, `split_all` with failure collection and output-coverage assertion; `tests/test_split.py` and `tests/fixtures/expected_children/`.
11. **`cli.py` — `split` subcommand** — `--dry-run`, `--check`, `--only`, the report; `tests/test_cli.py` extended.
12. **`publish.py` — `publish_domains` + `cli.py` — `publish domains`** — the loop over the unchanged `publish_workspace()`, `--apply` gate, `--only`, `--keep-going`; `tests/test_publish_domains.py`.
13. **`tests/test_no_hardcoded_identifiers.py` extension** — the 12 domain keys and child ids added to the forbidden list.
14. **The real split (offline)** — run against the committed parent, review the 12 diffs, commit `generated/workspaces/`, re-run and confirm a clean `git status`.
15. **`docs/domain-split.md` + the CI `split --check` job** — the invariant survives everyone who touches the repo afterwards.
16. **The real publishes (user-initiated)** — `publish domains --target demo-cloud` rehearsal, then `--apply`, then a third run proving idempotency across all 12.
