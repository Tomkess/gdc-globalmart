## Tasks — FEAT-004: Domain splitter: derive each domain workspace from the parent via transitive closure, prune the LDM to reachable datasets, and emit committed declarative JSON per domain

> Appetite: `l`  ·  Generated: 2026-09-18

- [ ] 1. Create `src/globalmart/maql.py`: `RefKind` (`StrEnum`: `METRIC`, `FACT`, `ATTRIBUTE`, `LABEL`, `DATASET`, `DATE_INSTANCE`), `MaqlRef` (`NamedTuple`: `kind`, `id`, `granularity: str | None`), and the single compiled `MAQL_REF_RE` matching `{<kind>/<id>}` with an optional quoted id and an optional `.<granularity>` suffix. No other module in the package may regex MAQL — add that statement to the module docstring.
       Pre: FEAT-002 task 6 complete (`GlobalmartError` base in `config.py`)
       AC: #7

- [ ] 2. Implement `iter_maql_refs(maql: str) -> Iterator[MaqlRef]` in `maql.py`, normalizing quoted ids to bare ids and splitting a `label`/`attribute` granularity suffix into `MaqlRef.granularity`. Preserve source order and do not de-duplicate — callers own that.
       Pre: task 1 complete (`MAQL_REF_RE`, `MaqlRef`, `RefKind`)
       AC: #7

- [ ] 3. Write `tests/test_maql.py` part 1: all five ref kinds extracted from a hand-written MAQL string; `{label/date_order.month}` yields `id="date_order"` and `granularity="month"`; a quoted id `{metric/"my metric"}` yields the unquoted id; MAQL with no refs yields nothing; braces inside a `WHERE` clause produce no phantom ref.
       Pre: task 2 complete (`iter_maql_refs`)
       AC: #7

- [ ] 4. Write `tests/test_maql.py` part 2 — the corpus assertion: run `iter_maql_refs` over every metric in `layouts/workspaces/globalmart/` (1075 expected) and assert every extracted id resolves to an existing metric, attribute, label, fact or dataset in the parent. Skip cleanly (not fail) when the real tree is absent, so the suite stays green before FEAT-001 task 31 lands.
       Pre: task 3 complete (`iter_maql_refs` proven on unit cases); FEAT-001 task 31 complete for the non-skipped path
       AC: #7, #8

- [ ] 5. Create `src/globalmart/refs.py` with `ObjectRef` (`NamedTuple`: `kind: RefKind`, `id: str`, `path: str`) and the private generic walker `_walk_refs(content: dict, prefix: str) -> Iterator[ObjectRef]`, recursing through dicts and lists and yielding an `ObjectRef` for every node shaped `{"type": <RefKind value>, "id": ...}` or `{"type": ..., "identifier": {"id": ...}}`, with `path` recording the dotted/indexed location. Generic by design so a widget variant nobody enumerated is still seen.
       Pre: task 1 complete (`RefKind`)
       AC: #7, #8

- [ ] 6. Add the dashboard generators to `refs.py`: `iter_dashboard_viz_refs(dashboard)` (section widgets' `insight`, `drills[].target`, `drillToInsight`, and any nested `visualizationObject` node), `iter_dashboard_filter_refs(dashboard)` (filter-context ids plus inline `dataSet` / `displayForm` refs), `iter_dashboard_plugin_refs(dashboard)`. All three delegate to `_walk_refs` and filter by kind, so no shape is enumerated twice.
       Pre: task 5 complete (`_walk_refs`, `ObjectRef`)
       AC: #7, #11

- [ ] 7. Add `iter_viz_refs(viz)` and `iter_filter_context_refs(fc)` to `refs.py`: classify `buckets[].items[].measure.definition.measure.item` as a metric, `attribute.displayForm` as a label, `filters[]` / `sorts[]` targets by their own `type`, and feed any `measure.definition.inline.maql` string through `maql.iter_maql_refs`, converting each `MaqlRef` to an `ObjectRef` with the inline path. `iter_filter_context_refs` covers `attributeFilters[].displayForm` and `dateFilters[].dataSet`.
       Pre: task 6 complete (dashboard generators establish the delegation pattern), task 2 complete (`iter_maql_refs` for inline MAQL)
       AC: #7

- [ ] 8. Write `tests/test_refs.py`: a visualization referenced from a section widget, from a drill target and from a `drillToInsight` are all found; a `{"type": "metric", "id": ...}` node nested deeper than any enumerated path is still yielded by the generic walk; `iter_viz_refs` classifies a metric, a label via `attribute.displayForm`, a fact inside an inline-MAQL measure and a date filter's `dataSet`, each with a `path` naming where it was found.
       Pre: task 7 complete (all five generators)
       AC: #7, #8

- [ ] 9. Build `tests/fixtures/mini_domains/mini_parent/` by trimming FEAT-001's `tests/fixtures/mini_globalmart/`: 9 datasets including the 3-hop join chain `fact_orders → dim_customer → dim_geo`, 2 shared dimensions, 1 SQL-backed dataset carrying `{{ datasource_schema }}`, and 2 date instances of which one is used by a single domain only. Commit as a YAML tree readable by `read_tree()`.
       Pre: FEAT-001 task 11 complete (`mini_globalmart` fixture), FEAT-001 task 9 complete (`read_tree` / `write_tree`)
       AC: #3, #5, #6

- [ ] 10. Extend `tests/fixtures/mini_domains/mini_parent/` with analytics: 12 metrics (one with a 3-deep `{metric/…}` chain, one referencing a `{label/…}` on a dataset no visualization touches), 6 visualization objects, 3 analytical dashboards (one deliberately mixed-domain), 1 filter context, 1 attribute hierarchy spanning two domains — with one of its attributes deliberately living on a dataset no visualization in either domain touches, so the pull-in rule is exercised: a filter-out design drops the hierarchy, the pull-in design retains it and brings that dataset into the LDM — 2 export definitions, 1 dashboard plugin, plus memory items and parameters split across the three domains. Leave one dataset reached by nothing at all, so it can be the `ldm_include` target in task 11.
       Pre: task 9 complete (mini LDM fixed, so analytics can reference real entity ids)
       AC: #7, #10, #11

- [ ] 11. Write `tests/fixtures/mini_domains/domains.yaml` — a 3-domain manifest in FEAT-003's schema: top level `version`, `parent_workspace_id`, `workspace_id_template`, `workspace_name_template`; per domain `key`, `label`, `description`, `workspace_id`, an optional `workspace_name` override on one domain, `dashboards`, `visualizations` and the **nested** `ai` block (`memory_item_ids`, `memory_item_tags`, `parameter_ids`, `agent_ids`, `knowledge_ids`) — there are no flat AI fields on `Domain`; a `shared:` block carrying one dashboard, one visualization and one `shared.ai` parameter, so the belongs-in-every-child rule is exercised; an `ldm_include` list on exactly one domain naming a dataset that domain's analytics do not reach, so declared LDM headroom is exercised and its separation from `shared:` and from coverage is testable; and an `unassigned:` block of `{id, reason}` exclusions under `dashboards` / `visualizations` / `ai`. Add a `conftest.py` fixture loading it via FEAT-003's `load_domains()`.
       Pre: task 10 complete (object ids fixed); FEAT-003 tasks 1, 3 and 5a complete (`load_domains`, `DomainManifest` with `by_key` / `keys` / `resolve_workspace_name` / `unassigned_ids`)
       AC: #1, #9, #14, #17, #18

- [ ] 12. Create `src/globalmart/prune.py` with the frozen `EntityIndex` dataclass (`attribute_to_dataset`, `label_to_dataset`, `fact_to_dataset`, `dataset_ids`, `date_instance_ids`, `references`, `grain`) and `build_entity_index(ldm) -> EntityIndex`, traversing `ldm.datasets[].attributes[].labels[]`, `.facts[]`, `.aggregated_facts[]`, `.references[].identifier.id`, `.grain[]` and `ldm.date_instances[]`.
       Pre: task 9 complete (a mini LDM to index), FEAT-001 task 9 complete (`read_tree`)
       AC: #3, #5

- [ ] 13. Add `resolve_entity(ref) -> str` and `DanglingReferenceError` to `prune.py`: map a `MaqlRef`/`ObjectRef` to its owning dataset id, resolving a `LABEL`/`ATTRIBUTE` whose id (or `<id>` before a granularity suffix) matches a date-instance id to that date instance rather than to a dataset, and raising `DanglingReferenceError` naming the ref and its `path` when nothing resolves.
       Pre: task 12 complete (`EntityIndex`), task 1 complete (`RefKind`, `MaqlRef`)
       AC: #6, #8

- [ ] 14. Implement `prune_ldm(ldm, dataset_ids, date_instance_ids) -> CatalogDeclarativeLdm` in `prune.py`: `deepcopy` first (the parent model must stay reusable across all 12 domains), keep only the named datasets and date instances sorted by `id`, leave each retained dataset's `attributes`/`labels`/`facts`/`grain`/`references` intact, and leave `{{ datasource_id }}` / `{{ datasource_schema }}` untouched. **Pruning is dataset-level only — decided, not open.** A retained dataset keeps every attribute, label and fact it has, even where today's analytics use a fraction of them: a label that looks unused may be a dataset's join grain or another dataset's `reference` target, so stripping it breaks the child in a way only an execution run would expose, and those columns are the headroom a child needs to author new metrics and visualizations. Column-level pruning is explicitly rejected and out of scope. Still compute and return per-dataset used/total attribute and fact counts into `DomainSplitResult.dataset_column_usage` for the report — that is the evidence any future column-pruning decision would be made on, never an input to pruning here.
       Pre: task 13 complete (`resolve_entity`, `DanglingReferenceError`)
       AC: #3, #4, #12

- [ ] 15. Implement `expand_join_ancestors(ldm, seed_dataset_ids) -> set[str]` in `prune.py`: worklist over `EntityIndex.references[d]`, following each edge **forward only** (a dataset's `references` point at the datasets it joins to), to fixpoint; an edge whose target is a date-instance id contributes to the date-instance set instead; resolve each retained dataset's `grain` entries the same way.
       Pre: task 14 complete (`prune_ldm` fixes the pruned-LDM shape)
       AC: #5, #6

- [ ] 16. Write `tests/test_prune.py` part 1: `build_entity_index` maps a nested label to its dataset and maps a date-instance-qualified label to the date instance, not to a dataset; `resolve_entity` on an unknown id raises `DanglingReferenceError` naming the id and path.
       Pre: task 15 complete (prune module feature-complete), task 9 complete (mini LDM)
       AC: #6, #8

- [ ] 17. Write `tests/test_prune.py` part 2 — the join-direction test: on the fixture's `fact_orders → dim_customer → dim_geo` chain, seeding `{fact_orders}` retains all three datasets; seeding `{dim_geo}` retains only `dim_geo`. Expected sets written out literally, hand-computed. Also assert `prune_ldm` does not mutate its input (digest the parent LDM before and after three successive prunes).
       Pre: task 16 complete (part 1 harness)
       AC: #4, #5

- [ ] 18. Create `src/globalmart/closure.py` with the frozen `DomainClosure` dataclass (`domain_key`, `dashboard_ids`, `visualization_ids`, `metric_ids`, `filter_context_ids`, `attribute_hierarchy_ids`, `export_definition_ids`, `dashboard_plugin_ids`, `dashboard_extension_ids`, `entity_refs`, `seed_dataset_ids`, `declared_dataset_ids`, `dataset_ids`, `date_instance_ids`, `why: dict[str, tuple[str, ...]]`) and the `build_closure(model, domain, manifest, index) -> DomainClosure` signature with the six stages stubbed. Implement **stage 1 (seed)**: seed from `domain.dashboards | manifest.shared.dashboards` and `domain.visualizations | manifest.shared.visualizations` — the `shared` block belongs in **every** child, and seeding it here is what makes stages 2–5 carry its visualizations, metrics and datasets into every child; omitting it would silently drop every shared object from all 12 children. Record a shared-seeded id in `why` as coming from `shared`, not from the domain's own list. Raise `DanglingReferenceError` for any seed id absent from the parent.
       Pre: task 13 complete (`DanglingReferenceError`), task 11 complete (`Domain` and `manifest.shared` available from the fixture manifest)
       AC: #1, #8, #17

- [ ] 18a. Extend closure **stage 1** with the declared LDM seed: `declared_dataset_ids = set(domain.ldm_include)`, each id checked against `ldm.datasets` and raising `DanglingReferenceError` naming the domain and the id when absent. Stage 5 unions it with `seed_dataset_ids` before `expand_join_ancestors`, so a declared dataset's join ancestors are pulled in exactly as any other retained dataset's, and the declared set is kept as its own field so `datasets_by_closure` and `datasets_declared` can be reported apart. `why` attributes a declared dataset to `ldm_include`, never to a domain's analytics. `ldm_include` widens **only** the LDM: it is never coverage of a dashboard, visualization or AI object (it takes no part in task 37's output-coverage check), and it is not the `shared:` block.
       Pre: task 18 complete (stage 1 seed and `DomainClosure`), FEAT-003 task 4a complete (`Domain.ldm_include` parsed and validated)
       AC: #18

- [ ] 19. Implement closure **stage 2** in `closure.py`: loop over retained dashboards with `iter_dashboard_viz_refs` / `iter_dashboard_filter_refs` / `iter_dashboard_plugin_refs`, adding visualization ids, filter-context ids, plugin ids and inline entity refs; repeat until `dashboard_ids` and `visualization_ids` stop growing (a drill target may itself be a dashboard). Record each addition's referrer in `why`.
       Pre: task 18 complete (stage 1 and `DomainClosure`), task 6 complete (dashboard generators)
       AC: #7, #11

- [ ] 20. Implement closure **stage 3** in `closure.py`: for each retained visualization, `iter_viz_refs` → `METRIC` ids into `metric_ids`, everything else into `entity_refs`, with `why` provenance carrying the visualization id and the ref `path`.
       Pre: task 19 complete (stage 2 populates `visualization_ids`), task 7 complete (`iter_viz_refs`)
       AC: #7

- [ ] 21. Implement closure **stage 4** — the transitive metric MAQL closure kept from the predecessor: a worklist over `metric_ids` running `iter_maql_refs(metric.content["maql"])`, appending `METRIC` refs back onto the worklist to fixpoint and routing all other kinds into `entity_refs`. A referenced metric absent from the parent raises `DanglingReferenceError`. This is the logic whose absence produced `"metrics … cannot be found"`.
       Pre: task 20 complete (stage 3 seeds `metric_ids`), task 2 complete (`iter_maql_refs`)
       AC: #7, #8

- [ ] 21a. Implement closure **stage 4b** in `closure.py` — reachable auxiliary objects, decided *before* datasets are resolved so their dependencies get pulled in rather than filtered out. Populate `attribute_hierarchy_ids` (a hierarchy is retained iff some retained visualization, dashboard or drill definition references it), `export_definition_ids` (its `requestPayload` target visualization/dashboard is retained), `dashboard_plugin_ids` (referenced by a retained dashboard), `dashboard_extension_ids` (its dashboard is retained) and the `filter_context_ids` stage 2 collected. Then feed every retained object's own references back into the closure — its attributes, labels, facts and datasets into `entity_refs`, any metric onto stage 4's worklist — so stage 5 pulls each hierarchy's attributes, their datasets and those datasets' join ancestors into the LDM as a consequence of the object travelling. Loop stages 2–4b together until nothing grows. **Never exclude an auxiliary object because a referent was not already retained; include the referent instead.** An object no retained object references is simply not in this domain: correct absence, recorded nowhere as a drop. A reference to an object absent from the *parent* raises `DanglingReferenceError` naming domain, referring object and reference — the one failure mode, and it aborts the whole split (AC #8). Record each retention's referrer in `why`.
       Pre: task 21 complete (stage 4 metric fixpoint), task 6 complete (dashboard generators), task 7 complete (`iter_viz_refs`)
       AC: #8, #11

- [ ] 22. Implement closure **stage 5** in `closure.py`: resolve every `entity_refs` entry through `resolve_entity` into `seed_dataset_ids` (or `date_instance_ids`) — `entity_refs` at this point already carries everything stage 4b's retained hierarchies, export definitions, plugins and extensions contributed — then call `expand_join_ancestors` over `seed_dataset_ids | declared_dataset_ids` to produce `dataset_ids`; add the date instances contributed by `references` and `grain`. Populate `why` for ancestor-only datasets with the chain that pulled them in, and for a dataset present solely because an auxiliary object needed it, name that object.
       Pre: task 21a complete (all refs collected, auxiliary objects settled), task 18a complete (`declared_dataset_ids`), task 15 complete (`expand_join_ancestors`)
       AC: #3, #5, #6, #18

- [ ] 23. Write `tests/test_closure.py`: the mixed-domain dashboard is retained (not silently dropped as under the predecessor's prefix rule) and the report-visible cross-domain pull is recorded in `why`; the 3-deep `{metric/…}` chain is fully retained; a manifest naming a non-existent dashboard raises `DanglingReferenceError` naming domain and id; `why` for a transitively-pulled metric names the dashboard and visualization it came through. Add the stage-4b pull-in assertions: the spanning attribute hierarchy is retained in every domain that references it, the dataset owning the attribute no visualization in that domain touches is in `dataset_ids` **because** the hierarchy travelled (with `why` naming it), and the negative form — deciding hierarchy retention after the LDM is pruned — leaves the hierarchy out of both children, which is the design this assertion exists to prevent. Add the stage-1 `ldm_include` assertions: a declared dataset is in `declared_dataset_ids` and in `dataset_ids` with its join ancestors, `why` attributes it to `ldm_include`, it is absent from `seed_dataset_ids`, and a declared id absent from `ldm.datasets` raises `DanglingReferenceError`.
       Pre: task 22 complete (all six stages), task 21a complete (stage 4b), task 18a complete (declared seed), task 11 complete (mini manifest)
       AC: #7, #8, #11, #18

- [ ] 24. Create `src/globalmart/verify.py` with `ChildVerificationError` and the **under-pruning gate** of `verify_child(child_model, domain_key, closure) -> None`: re-walk every retained metric (via `maql.iter_maql_refs`), visualization, dashboard and filter context (via `refs.py`) and assert each referenced id resolves inside the child — metric in `analytics.metrics`, entity in the child's own `EntityIndex`, dataset/date instance in the pruned LDM. Collect **all** violations as `(domain, object_id, reference, reason)` before raising.
       Pre: task 22 complete (`DomainClosure`), task 12 complete (`build_entity_index` re-runnable on a pruned LDM)
       AC: #8

- [ ] 25. Add the **over-pruning gate** to `verify.py`: assert every dataset id in `child_model.ldm.datasets` is in `closure.dataset_ids`, and that every one of those is accounted for — a `seed_dataset_ids` member (which includes datasets required by retained attribute hierarchies, export definitions, plugins and extensions), a `declared_dataset_ids` member from `domain.ldm_include`, or a join ancestor of one of those. A dataset explained by none of them is a build failure; a dataset present solely because a retained hierarchy or a declared include needed it is legitimately used and must pass. Also assert every retained dataset's `references` targets are present in the pruned LDM. Add no column-level assertion: retained datasets keep all their columns by design.
       Pre: task 24 complete (`verify_child` skeleton and violation collection), task 21a complete (auxiliary pull-ins present in the closure), task 18a complete (`declared_dataset_ids`)
       AC: #4, #5, #18

- [ ] 26. Write `tests/test_verify.py` part 1 — under-pruning: hand-build a child whose retained metric MAQL references a `{label/…}` on a dataset removed from the LDM and assert `ChildVerificationError` names the domain, the metric id and the label ref; a retained dataset with a `references` target absent from the pruned LDM also raises.
       Pre: task 25 complete (both gates implemented)
       AC: #8

- [ ] 27. Write `tests/test_verify.py` part 2 — **the defect-#2 regression test**: take a correctly generated child, inject one extra dataset that no retained object references and that the domain does not declare in `ldm_include`, and assert `verify_child` raises naming that dataset. Assert the complements too, so the gate can never be read as "unreferenced by analytics ⇒ unused": a dataset present solely because a retained attribute hierarchy or export definition required it passes, and so does one present solely because `ldm_include` declared it. Then the degenerate form — build a child carrying the full unpruned parent LDM (exactly what `"ldm": model["ldm"]` shipped 12 times) and assert it fails with the unused datasets listed.
       Pre: task 26 complete (part 1 harness)
       AC: #4

- [ ] 28. Create `src/globalmart/ai_context.py`: `AiContextSelection` dataclass and `filter_ai_context(model, domain, manifest) -> AiContextSelection`, keeping the `memoryItems`, parameters, agent personalities and AI-knowledge objects selected by the **nested** `domain.ai` (`memory_item_ids`, `parameter_ids`, `agent_ids`, `knowledge_ids`, plus every memory item whose tags intersect `domain.ai.memory_item_tags` — the rule-based selector FEAT-003 defines, which must be honoured here or a tagged item silently misses its child) **unioned with `manifest.shared.ai`**, which belongs in every child. There are no flat AI fields on `Domain`. Raise `MissingAiContextError` naming any selected id absent from the parent. Cross-domain AI memory in a child is a defect, and a `shared.ai` item missing from a child is equally one (STEERING § Portability Contract).
       Pre: task 11 complete (nested `domain.ai` and `manifest.shared.ai` in the fixture manifest), FEAT-001 task 31a complete (AI-context objects present in the captured model)
       AC: #10, #17

- [ ] 28a. Write the shared-block test covering closure seeding and AI filtering together: for each of the mini manifest's 3 domains, assert `build_closure` retains every `shared.dashboards` and `shared.visualizations` id (and, transitively, the visualizations, metrics and datasets those shared objects reach), that `why` attributes them to `shared` rather than to the domain's own list, and that `filter_ai_context` returns every `shared.ai` selection in all three domains while still excluding another domain's own `ai` selections. Add the negative form — seeding from `domain.dashboards` alone, or filtering from `domain.ai` alone — and assert it drops the shared objects from two of the three children, which is the silent drop this test exists to prevent. Once `split_all` lands (task 37), the same assertion runs end-to-end over the generated children in `tests/test_split.py`.
       Pre: task 28 complete (`filter_ai_context` with the `shared.ai` union), task 22 complete (all six closure stages, seeded with `shared` in task 18), task 11 complete (mini manifest carries a `shared:` block)
       AC: #17

- [ ] 29. Extend `src/globalmart/layout_io.py` with `stable_sort_model(model)`, lifting FEAT-001 normalizer pass 5's sort keys into a reusable function so YAML and JSON emission cannot drift; refactor normalizer pass 5 to call it, keeping FEAT-001's tests green unmodified.
       Pre: FEAT-001 task 20 complete (pass 5 sort keys defined), FEAT-001 task 22 complete (pass-5 tests exist to prove no regression)
       AC: #2

- [ ] 30. Add `write_model_json(model, path)` and `read_model_json(path)` to `layout_io.py`: write via `json.dumps(deep_sort(stable_sort_model(model).to_api().to_dict(camel_case=True)), sort_keys=True, indent=2, ensure_ascii=False)` plus a trailing newline; read back into a `CatalogDeclarativeWorkspaceModel`. Add `generated/**/*.json text eol=lf` to `.gitattributes`.
       Pre: task 29 complete (`stable_sort_model`)
       AC: #2

- [ ] 31. Extend `tests/test_layout_io.py`: `write_model_json` produces byte-identical output across two writes of the same model; `read_model_json(write_model_json(m))` round-trips equal under `to_api().to_dict(camel_case=True)`; no `set` iteration order leaks into the output (write the same model from two differently-ordered in-memory constructions and assert equal bytes).
       Pre: task 30 complete (JSON writer/reader)
       AC: #2

- [ ] 32. Create `src/globalmart/split.py` with the `DomainSplitResult` dataclass (`domain_key`, `workspace_id`, `label`, `workspace_name` — from `manifest.resolve_workspace_name(domain)`, never concatenated here — `counts`, `datasets_retained`, `datasets_by_closure`, `datasets_declared`, `datasets_pruned`, `datasets_from_ancestors_only`, `dataset_column_usage`, `date_instances_retained`, `metrics_from_maql_closure`, `hierarchies_retained`, `export_definitions_retained`, `plugins_retained`, `extensions_retained` — what each child kept; there is deliberately no `dropped_*` counterpart, since an object no retained object references is correctly absent rather than lost and an unsatisfiable dependency is an error, not a report line — `ai_context_ids`, `digest`, `path`) and `SplitResult` (`domains`, `unassigned_ids` — from `manifest.unassigned_ids()`, the flattened `Exclusion` ids — `shared_ids`, `coverage_ok`, `failures`).
       Pre: task 22 complete (`DomainClosure` supplies the counts), FEAT-001 task 7 complete (`ObjectCounts`), FEAT-002 task 14 complete (`model_digest`)
       AC: #1, #3

- [ ] 33. Implement `assemble_child(model, closure, domain, ai_selection) -> CatalogDeclarativeWorkspaceModel` in `split.py`: pruned LDM (closure-reached datasets, `closure.declared_dataset_ids`, and the join ancestors of both) plus the closure-filtered `metrics`, `visualization_objects`, `analytical_dashboards`, `filter_contexts`, and the filtered AI context (`domain.ai` ∪ `manifest.shared.ai`). The closure already carries the `shared` dashboards and visualizations, so filtering by it is what puts shared objects into every child. Never mutate the parent model.
       Pre: task 32 complete (`DomainSplitResult`), task 14 complete (`prune_ldm`), task 28 complete (`filter_ai_context`)
       AC: #1, #3, #10

- [ ] 34. Materialize the previously-emptied collections in `assemble_child` from the closure's id sets, never by filtering against the pruned LDM: `attribute_hierarchies` = `closure.attribute_hierarchy_ids`, `export_definitions` = `closure.export_definition_ids`, `dashboard_plugins` = `closure.dashboard_plugin_ids`, `analytical_dashboard_extensions` = `closure.dashboard_extension_ids`, `filter_contexts` = `closure.filter_context_ids`. Stage 4b (task 21a) already decided each by reachability and already fed its references into `entity_refs`, so the attributes, labels, facts, datasets and join ancestors each retained object needs are in the LDM **because** the object travelled. Never exclude one of these objects for referencing something an earlier pass omitted — the referent is pulled in instead. Record what each child retained in `hierarchies_retained` / `export_definitions_retained` / `plugins_retained` / `extensions_retained`; there is deliberately **no** `dropped_*` list, because an object no retained object references is correctly absent from that domain rather than lost, and a dependency missing from the parent is a loud non-zero-exit failure of the whole run (task 21a), not a report line. None of the five is ever unconditionally `[]`.
       Pre: task 33 complete (`assemble_child` core), task 21a complete (stage 4b settles the five id sets)
       AC: #11

- [ ] 35. Implement `split_domain(model, domain, manifest, index) -> DomainSplitResult` in `split.py`: `build_closure(model, domain, manifest, index)` → `prune_ldm` → `assemble_child` → `verify_child` → populate the result (including `workspace_name` via `manifest.resolve_workspace_name(domain)` and `digest` via `model_digest`). It returns a model and a result but writes nothing — writing is `split_all`'s job, so verification can abort before any file exists.
       Pre: task 34 complete (assembly complete), task 25 complete (`verify_child`)
       AC: #1, #3, #4, #8

- [ ] 36. Implement `split_all(model, manifest, *, only=None) -> tuple[SplitResult, dict[str, model]]` in `split.py`: iterate `manifest.keys()` in order, **collect every domain's failure before raising** so one run reports all problems, and return the assembled models without writing. Raise a combined error if any domain failed — the split is all-or-nothing (AC #8).
       Pre: task 35 complete (`split_domain`)
       AC: #1, #8

- [ ] 37. Add the output-coverage assertion to `split_all`: every parent dashboard and visualization object must appear in at least one domain's closure (which now includes the `shared` seed) or in `manifest.unassigned_ids()` — the flattened ids of the `Exclusion(id, reason)` entries under `unassigned.dashboards` / `unassigned.visualizations` / `unassigned.ai`, read through the manifest accessor rather than flattened here; otherwise raise `CoverageError` listing the unreached ids. `ldm_include` takes no part in this check — it widens a child's LDM and never covers a dashboard, visualization or AI object. This is FEAT-004's own check on its output, independent of FEAT-003's input validation.
       Pre: task 36 complete (all closures available in one place)
       AC: #9

- [ ] 38. Write `tests/test_split.py` part 1: `split_all` on `mini_domains` yields exactly 3 children; per-domain `datasets_retained` equals the hand-computed number and is strictly less than the fixture's 9; `datasets_from_ancestors_only` is non-zero for the domain whose seed is a fact table; the date instance used by one domain appears only in that child.
       Pre: task 37 complete (`split_all` with coverage), task 11 complete (mini manifest)
       AC: #3, #5, #6

- [ ] 39. Write `tests/test_split.py` part 2 — the pull-in rule end to end, asserted individually since all five collections were unconditionally `[]` in the predecessor. The spanning attribute hierarchy lands in **every** child whose retained analytics reference it, and in each such child the datasets of *all* its attributes are in the pruned LDM — including the fixture attribute whose dataset the analytics closure alone would never have reached, with `why` naming the hierarchy as the reason it came in. Assert the hierarchy is never dropped from a child for naming an attribute closure missed. A child that references it nowhere simply does not carry it: assert that absence directly and assert that nothing reports it as a drop (there is no `dropped_*` list). Same shape for the 2 export definitions and the dashboard plugin. Then the unsatisfiable case: a variant fixture whose hierarchy names an attribute present in no parent dataset makes the run exit non-zero naming the hierarchy and the attribute and leaves the output directory empty.
       Pre: task 38 complete (split harness), task 34 complete (the five collections), task 21a complete (stage 4b)
       AC: #8, #11

- [ ] 40. Write `tests/test_split.py` part 3: the pairwise intersection of the three children's `ai_context_ids` is exactly the `shared.ai` id set — domain-selected items never cross, shared items always do; every `shared.dashboards` / `shared.visualizations` id appears in all three generated children (AC #17, the end-to-end form of task 28a); a memory item pulled in only by a `memory_item_tags` match is present in that child and absent from the others; a domain selecting a memory-item id absent from the parent raises `MissingAiContextError` naming it; every generated child's `dataSourceId` is `{{ datasource_id }}`, its SQL statements still contain `{{ datasource_schema }}`, and a grep of the serialized child for `globalmart-motherduck` returns zero hits.
       Pre: task 38 complete (split harness), task 28a complete (`filter_ai_context` and the shared seed proven in isolation)
       AC: #10, #12, #17

- [ ] 40a. Write `tests/test_split.py` part 3b — declared LDM headroom (AC #18): the domain whose fixture manifest carries `ldm_include` has each declared dataset in its generated `ldm.datasets` together with that dataset's join ancestors and with every one of its attributes, labels and facts intact, so a new metric could be authored on it; `datasets_declared` counts them while `datasets_by_closure` does not, and `datasets_retained` is their sum net of overlap; `verify_child` accepts the child rather than flagging a declared dataset as unused; the two domains declaring nothing do not carry it; a declared id absent from the parent fails the run naming the domain and the id; and `ldm_include` changes no coverage outcome — the same manifest with the `ldm_include` block removed yields an identical `SplitResult.coverage_ok` and identical `unassigned_ids`.
       Pre: task 40 complete (part 3 harness), task 18a complete (declared seed), task 25 complete (over-pruning gate accepts declared datasets), task 11 complete (fixture manifest carries `ldm_include`)
       AC: #18

- [ ] 41. Write `tests/test_split.py` part 4 — failure semantics: removing a dashboard from the manifest without adding it to the unassigned allow-list raises `CoverageError` naming it; a fixture where domain 2 of 3 fails verification leaves the output directory **empty** (domain 1's file is not written either); the raised error names every failing domain, not only the first.
       Pre: task 37 complete (coverage + failure collection), task 27 complete (a known-failing child shape)
       AC: #8, #9

- [ ] 42. Generate `tests/fixtures/expected_children/` — the three expected child JSONs for `mini_domains`, written by the pipeline and hand-reviewed once — plus a test asserting `split_all` regenerates each byte-identically and that a second run produces identical bytes (AC #2 expressed without git).
       Pre: task 38 complete (split proven correct on the fixture), task 30 complete (`write_model_json`)
       AC: #1, #2

- [ ] 43. Add the `split` subcommand to `src/globalmart/cli.py`: `globalmart split [--domains-file config/domains.yaml] [--from layouts/workspaces/globalmart] [--out generated/workspaces] [--only sales,hr] [--dry-run] [--check]`. The manifest lives at `config/domains.yaml`, beside `config/targets.yaml` — FEAT-003 owns that location. Writes **local files only**, so per ADR 002 it takes `--dry-run` (report, write nothing) and never `--apply`. Loads the parent with `read_tree()` and the manifest with `load_domains()`, runs `split_all`, writes each model with `write_model_json`.
       Pre: task 36 complete (`split_all`), task 30 complete (`write_model_json`), FEAT-002 task 30 complete (`cli.py` publish group shape)
       AC: #1, #2

- [ ] 44. Implement `--check` and the split report in `cli.py`: `--check` regenerates in memory and exits 1 naming every `generated/workspaces/*.json` whose bytes differ from what is committed (the CI gate against hand-edited generated files); the report prints, per domain, `datasets_retained` broken out as `hr: 18 datasets (14 by closure, 4 declared)` so declared widening from `ldm_include` stays visible and cannot creep unnoticed, plus `datasets_pruned` / `datasets_from_ancestors_only`, `metrics_from_maql_closure`, the per-dataset used/total attribute and fact counts from `dataset_column_usage` (evidence only — all columns are kept), the `*_retained` lists for hierarchies, export definitions, plugins and extensions, the objects each child carries from the manifest's `shared` block, and the datasets pulled in solely by a single dashboard or solely by one retained hierarchy or export definition (from `closure.why`). It prints no "dropped" section: an object no retained object references is correctly absent, not a loss. Exit 1 on any closure, verification or coverage failure.
       Pre: task 43 complete (`split` subcommand wired)
       AC: #2, #11, #16, #18

- [ ] 45. Extend `tests/test_cli.py`: `split --dry-run` writes no file and prints the report; `split` then `split --check` exits 0; `--check` after hand-editing one generated file exits 1 naming that file; `--only sales` writes exactly one file.
       Pre: task 44 complete (report and `--check`)
       AC: #1, #2, #16

- [ ] 46. Add `publish_domains(sdk, manifest, profile, *, models, only, apply, no_backup, standalone_copy, keep_going) -> list[PublishResult]` to `src/globalmart/publish.py`: a loop calling the **unchanged** `publish_workspace()` once per domain with `workspace_id=resolved_workspace_id(profile, domain.workspace_id)` and `workspace_name=manifest.resolve_workspace_name(domain)` — the manifest renders the display name (per-domain `workspace_name` override else `workspace_name_template`); this module never concatenates `"GlobalMart — " + label` itself, and `domain.label` alone is not the published name. Nothing in `publish.py` may gain knowledge of domains beyond the manifest it is handed. Stop at the first failure unless `keep_going`, listing the domains not attempted.
       Pre: FEAT-002 task 26 complete (`publish_workspace`, `resolved_workspace_id`, `--workspace-name`), task 11 complete (`DomainManifest`)
       AC: #13, #14

- [ ] 47. Add the `publish domains` subcommand to `cli.py`: `globalmart publish domains --target <profile> [--in generated/workspaces] [--only …] [--apply] [--no-backup] [--standalone-copy] [--keep-going]`, reading each child with `read_model_json` and never re-deriving from the parent. Writes to a live org, so it takes `--apply` and has no `--dry-run`; `--no-backup` is refused without `--apply`, matching `publish parent`. Head a non-`--apply` run with the same `REHEARSAL — no writes.` line and print all 12 diffs.
       Pre: task 46 complete (`publish_domains`), task 30 complete (`read_model_json`)
       AC: #13

- [ ] 48. Write `tests/test_publish_domains.py` part 1 against FEAT-002's `FakeSdk` with `apply=True`: exactly one `put_declarative_workspace` per domain; each `workspace_id` equals `globalmart-<domain>` after `resolved_workspace_id`, including under a non-empty `workspace_id_prefix`; each `CatalogWorkspace` name equals `manifest.resolve_workspace_name(domain)` (`GlobalMart — Sales` for `label: Sales` under the default template, and the per-domain `workspace_name` override on the domain that sets one) — asserted against the manifest helper, never against a string the test builds itself.
       Pre: task 46 complete (`publish_domains`), FEAT-002 task 24 complete (`FakeSdk`)
       AC: #13, #14

- [ ] 49. Write `tests/test_publish_domains.py` part 2: without `--apply`, zero write calls across all domains while a diff is still produced per child; publishing twice against a `FakeSdk` that serves back what it was given yields `changed is False` for every domain on the second pass; `--only sales,hr` touches exactly two workspaces; a per-child failure stops the loop and the report lists the domains not attempted, while `--keep-going` continues and still exits non-zero.
       Pre: task 48 complete (part 1 harness)
       AC: #13

- [ ] 50. Extend `tests/test_no_hardcoded_identifiers.py` with the 12 domain keys (`sales`, `ecommerce`, `product`, `customer`, `loyalty`, `inventory`, `marketing`, `finance`, `store_ops`, `hr`, `risk`, `real_estate`) and the `globalmart-<domain>` ids, asserting none appears in `src/globalmart/**/*.py` outside comments — the predecessor kept the domain list in four separate places. **Carry FEAT-003's allow-list**: `src/globalmart/domain_bootstrap.py` is exempt (it holds the one-time `SEED_DOMAINS` pairs used only to generate the first manifest) and so is `config/domains.yaml`. Without the exemption this test and FEAT-003's `tests/test_single_source_of_domains.py` contradict each other. Better still, import the allow-list from that test rather than restating it, so the two cannot diverge.
       Pre: task 47 complete (all FEAT-004 source modules written)
       AC: #15

- [ ] 51. Run the real split offline: `globalmart split` against the committed parent tree and `domains.yaml`. Review the report — each of the 12 `datasets_retained` figures must be plausibly narrow (an HR child in the tens, not 225) and the coverage section must be clean. Review the 12 generated diffs as the artifact, then commit `generated/workspaces/`.
       Pre: tasks 44, 45 complete (CLI proven on the fixture); FEAT-001 task 31 complete (real parent tree); FEAT-003 complete (real `domains.yaml`)
       AC: #1, #3, #4, #9

- [ ] 52. Verify determinism on the real output: re-run `globalmart split` and assert `git status` is clean. If not, isolate the unstable field, add it to `stable_sort_model`, and repeat until the second run is a byte-for-byte no-op.
       Pre: task 51 complete (real output committed)
       AC: #2

- [ ] 53. Add regression pins for the real split: a test asserting each domain's `datasets_retained` stays within a committed band (recorded in `docs/domain-split.md`), so a future closure change that quietly re-broadens a child to near-225 fails CI rather than shipping.
       Pre: task 52 complete (stable real figures to pin)
       AC: #3, #4

- [ ] 54. Write `docs/domain-split.md`: the six closure stages in order (including the `shared`-block union and the `ldm_include` declared seed in stage 1, why a shared object missing from any child is a build failure, and stage 4b's pull-in rule — an object that travels brings everything it requires with it, dependencies are never filtered out, and an object nothing reaches is correctly absent rather than dropped), the prune rules and the forward-only join direction, that pruning is dataset-level only and a retained dataset keeps all its columns (and why column-level pruning is rejected), what `ldm_include` is for and how the report separates declared datasets from closure-reached ones, what "fails loudly" means and the all-or-nothing guarantee, how to read the split report, the recorded per-domain `datasets_retained` band, and the explicit statement that a generated file is never hand-edited (fix the parent or `domains.yaml` and regenerate).
       Pre: task 53 complete (real figures recorded), task 44 complete (final report shape)
       AC: #3, #16

- [ ] 55. Add the CI job running `uv run globalmart split --check` beside FEAT-001's `normalize --check`, plus `uv run pytest tests/ -x -q`, so a hand-edited generated file or a parent change not re-split fails the build.
       Pre: task 52 complete (committed output is stable), task 44 complete (`--check`)
       AC: #16

- [ ] 56. **Requires explicit user approval to run against a live host.** Run `globalmart publish domains --target demo-cloud` (rehearsal, no `--apply`) and read the report: all 12 workspace ids named, zero unresolved placeholders and zero foreign datasource ids per child, `applied is False`, nothing written to the org.
       Pre: task 55 complete (offline suite and CI green), task 51 complete (generated children committed); credentials for `petertomko.demo.cloud`
       AC: #12, #13

- [ ] 57. **Requires explicit user approval to run against a live host.** Run `globalmart publish domains --target demo-cloud --apply`, confirm a backup tree per child and that each workspace carries its pruned LDM and its own display name from `domains.yaml`; then run a third time with `--apply` and confirm `changed is False` for all 12.
       Pre: task 56 complete (rehearsal report reviewed and accepted)
       AC: #13, #14

- [ ] 58. **Requires explicit user approval to run against a live host.** Spot-check the narrowing in the live org: open the `hr` child and confirm its dataset list matches `datasets_retained` from the report and contains no unrelated retail tables, and that its AI memory contains no other domain's items. Record the outcome in `docs/domain-split.md`.
       Pre: task 57 complete (children published)
       AC: #3, #4, #10
