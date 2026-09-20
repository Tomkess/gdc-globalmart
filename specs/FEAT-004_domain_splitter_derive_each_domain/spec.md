---
abandoned_at: null
abandoned_reason: null
appetite: l
blocked_at: null
blocked_by: null
confidence: high
created: '2026-09-18'
cycle: null
depends_on:
- feat-001
- feat-002
- feat-003
enables:
- feat-006
goal: goal-01
id: feat-004
name: 'Domain splitter: derive each domain workspace from the parent via transitive
  closure, prune the LDM to reachable datasets, and emit committed declarative JSON
  per domain'
sources: []
status: done
tags: []
updated: '2026-09-20'
---

## Summary

This is the feature the whole repo is shaped around: *"keep development on top of one workspace
(parent) and then script will just ensure the separation."* The parent `globalmart` workspace
(225 datasets, 1075 metrics, 384 visualizations, 32 dashboards) is the only editing surface; the 12
domain workspaces are derived from it deterministically, committed as reviewable declarative JSON
under `generated/workspaces/globalmart-<domain>.json`, and published through FEAT-002's
`publish_workspace()`.

The splitter takes FEAT-003's explicit `domains.yaml` membership, expands it by transitive closure
(dashboard → visualization → metric → metric → LDM entity → dataset → join ancestors → date
instance), **prunes the LDM to exactly the datasets that closure reaches**, filters the AI-context
channels per domain, and fails loudly rather than emit a child that cannot compute.

The predecessor `publish_domain_workspaces.py` got the metric closure right and everything else
wrong: it copied the **full 225-dataset LDM into every child** (`"ldm": model["ldm"]`), copied
`memoryItems` and `parameters` verbatim into all 12, hardcoded `attributeHierarchies`,
`exportDefinitions`, `dashboardPlugins` and `analyticalDashboardExtensions` to `[]`, inferred
membership from a `viz_<domain>_` id prefix (silently dropping any mixed-domain dashboard), rewrote
the datasource by `json.dumps(model).replace('"globalmart-postgres"', …)` — a no-op, since the
layout carried `globalmart-motherduck` — and had the domain list hardcoded in four places, with no
dry run, no diff, no verification and no tests. An "HR workspace" that still exposes every retail
table is not a domain workspace; it distorts exactly the AI search/routing evaluation these
workspaces exist for. Fixing that is the point of this feature.

## Appetite

`l` — 2–4 weeks

## Acceptance Criteria

- [x] 1. Given the committed parent tree and `domains.yaml`, when `globalmart split` runs, then
      exactly one `generated/workspaces/globalmart-<domain>.json` file is written per domain in the
      manifest (12 today: sales, ecommerce, product, customer, loyalty, inventory, marketing,
      finance, store_ops, hr, risk, real_estate), and no file is written for any key absent from the
      manifest.
- [x] 2. Given an unchanged parent tree and manifest, when `globalmart split` is run twice, then
      `git diff generated/workspaces/` is empty — the emitted JSON is byte-stable (sorted keys,
      stable-sorted lists, fixed indent, trailing newline).
- [x] 3. Given the `hr` domain, when its generated file is inspected, then `ldm.datasets` contains
      strictly fewer than 225 datasets, and every dataset present is reachable from **some** object
      retained in that child — a metric, visualization, dashboard, filter context, attribute
      hierarchy, export definition, dashboard plugin or dashboard extension — or is named in that
      domain's `ldm_include`, or is a join ancestor of one that is. Each retained dataset carries all
      of its attributes, labels and facts: pruning is dataset-level only.
- [x] 4. Given any generated child, when every dataset in its LDM is checked against the union of
      LDM entity references made by **every** object that child retains (plus that domain's declared
      `ldm_include` and the join-ancestor closure over both), then the set of datasets accounted for
      by none of those is empty — a dataset that neither a retained object requires nor the manifest
      declares is a build failure, not a warning. (This is the predecessor's defect #2, asserted.) A
      dataset pulled in solely by a retained attribute hierarchy or export definition, or solely by
      `ldm_include`, is legitimately used and passes this check; it is not "unused" merely because no
      visualization references it today.
- [x] 5. Given any retained dataset — whether it arrived through analytics closure, through a
      retained attribute hierarchy or export definition, or through `ldm_include` — when the child is
      generated, then every dataset named in its `references[].identifier.id` chain is present
      transitively, so no retained dataset has a dangling join.
- [x] 6. Given the parent's 2 date instances, when a child is generated, then `ldm.date_instances`
      contains exactly those date instances required by objects retained in that child — its metrics,
      visualization buckets, dashboard filter contexts, attribute hierarchies, export definitions,
      retained dataset references or `ldm_include` datasets. A date instance a retained object needs
      is pulled in; one nothing in the child needs is absent.
- [x] 7. Given a retained metric whose MAQL references another metric via `{metric/<id>}`, when the
      child is generated, then that referenced metric is present, transitively to fixpoint — a child
      must never fail to load with "metrics … cannot be found".
- [x] 8. Given a domain whose closure references an object that does not exist in the parent (a
      dangling dashboard id, a missing metric, a label whose dataset was pruned), when `split` runs,
      then it exits non-zero naming the domain, the referring object id and the offending reference,
      and writes **no** file for any domain — the split is all-or-nothing.
- [x] 9. Given the full manifest, when `split` completes, then every one of the parent's 32
      dashboards and 384 visualization objects is either assigned to at least one domain, carried by
      the manifest's `shared:` block, or listed in the manifest's `unassigned:` exclusions (read
      through `manifest.unassigned_ids()`); anything else fails the run with the object ids listed.
- [x] 10. Given a domain's nested AI-context selection in `domains.yaml` (`ai.memory_item_ids`,
      `ai.memory_item_tags`, `ai.parameter_ids`, `ai.agent_ids`, `ai.knowledge_ids`), when the child
      is generated, then its `memoryItems`, parameters, agent personalities and AI knowledge contain
      exactly that domain's selection — ids plus every memory item carrying one of the listed tags —
      unioned with `shared.ai`, and nothing else: no item selected only by another domain appears
      (cross-domain AI memory leak is a defect, STEERING § Portability Contract).
- [x] 11. Given the parent's `attributeHierarchies`, `exportDefinitions`, `dashboardPlugins`,
      `analyticalDashboardExtensions` and `filterContexts`, when a child is generated, then
      membership is decided by **reachability from that domain's retained analytics, and inclusion
      pulls dependencies in** — the same uniform principle that already governs metrics, where a
      metric referencing `{metric/<id>}` pulls that metric in. Concretely: an `attributeHierarchy` is
      retained iff some retained visualization, dashboard or drill definition in that domain
      references it, and once retained, every attribute it names — plus each attribute's dataset and
      that dataset's join ancestors — is pulled into the pruned LDM. The same holds for
      `exportDefinitions`, `dashboardPlugins`, `analyticalDashboardExtensions` and `filterContexts`.
      No such object is ever excluded because an earlier pass happened not to retain one of its
      referents; the referent is included instead. An object that no retained object references is
      simply not part of that domain — its absence is correct, is not a loss, and is never reported
      as a drop. The only failure mode is a dependency that **cannot** be satisfied because the
      referenced object does not exist in the parent at all: that is a loud, named, non-zero-exit
      error and the whole split writes nothing (AC #8's all-or-nothing guarantee), never a silent
      omission. None of the five collections is ever unconditionally emptied.
- [x] 12. Given a generated child, when it is searched for datasource identifiers, then every
      `dataSourceId` is the `{{ datasource_id }}` token and every SQL-backed dataset still carries
      `{{ datasource_schema }}` — substitution happens at publish time through `resolve.py`, and no
      code path in this feature performs string replacement over serialized JSON.
- [x] 13. Given `globalmart publish domains --target <profile>` **without** `--apply`, then every
      child is resolved, asserted and diffed against the target, nothing is written to the org, and
      the report names each of the 12 workspace ids; given the same command **with** `--apply`, then
      each child is published through FEAT-002's `publish_workspace()` and a second run reports
      `changed is False` for all 12.
- [x] 14. Given a domain in `domains.yaml`, when its workspace is published, then the workspace
      display name is `manifest.resolve_workspace_name(domain)` — the per-domain `workspace_name`
      override when present, otherwise the manifest's `workspace_name_template` rendered with the
      domain's `label` — passed through FEAT-002's existing `--workspace-name` parameter. No code in
      this feature concatenates that string itself, and `TargetProfile` gains no domain-aware field.
- [x] 15. Given a grep of `src/globalmart/**/*.py`, when searching for any of the 12 domain keys or
      any `globalmart-<domain>` workspace id, then zero occurrences are found outside tests — the
      domain list lives only in `domains.yaml` (the predecessor had it in four places).
- [x] 16. Given a hand-edited `generated/workspaces/globalmart-sales.json`, when
      `globalmart split --check` runs in CI, then it exits 1 naming the file that does not match what
      the parent plus the manifest would produce.
- [x] 17. Given a manifest whose `shared:` block names dashboards, visualizations and `shared.ai`
      selections, when `split` runs, then **every** generated child contains every one of those
      objects — the shared dashboards and visualizations are seeded into each domain's closure
      alongside that domain's own, their transitive closure and the datasets it reaches are retained
      in each child's pruned LDM, and each child's AI context is `domain.ai` ∪ `shared.ai`. A shared
      object missing from any child is a build failure, not a warning: silently dropping the `shared`
      block from all 12 children is the same class of defect as the predecessor's silently dropped
      mixed-domain dashboards.
- [x] 18. Given a domain declaring `ldm_include: [dim_store, dim_geo]` in `domains.yaml`, when its
      child is generated, then every declared dataset is present in `ldm.datasets` together with its
      join ancestors — added to the closure seed and expanded exactly as any other retained
      dataset's — with all of its attributes, labels and facts intact, so a new metric or
      visualization can be authored in the child on a table today's dashboards never touch. The
      split report shows the two sources separately, e.g. `hr: 18 datasets (14 by closure, 4
      declared)`, so declared widening stays visible and cannot creep unnoticed. A declared dataset
      id absent from the parent fails the run naming the domain and the id. `ldm_include` widens only
      the LDM: it is never coverage of a dashboard, visualization or AI object, and it is not the
      `shared:` block.

## Scope

- A closure engine (`closure.py`) that expands a domain's manifest seed — that domain's dashboards
  and visualizations **unioned with the manifest's `shared:` dashboards and visualizations, which
  belong in every child** — into the full retained object
  set: dashboards → visualization objects → metrics → transitive metric MAQL closure → reachable
  attribute hierarchies, export definitions, plugins, dashboard extensions and filter contexts → LDM
  entity references (`{fact/…}`, `{attribute/…}`, `{label/…}`, `{dataset/…}`) made by **all** of them
  → owning datasets → join ancestors → date instances. One uniform rule throughout: reachability
  decides what travels, and whatever travels pulls its dependencies in with it.
- An LDM pruner (`prune.py`) that builds the entity→dataset index from `model.ldm`, walks the
  `references` join graph to fixpoint, and emits a pruned `CatalogDeclarativeLdm` containing the
  closure-reached datasets, the domain's declared `ldm_include` datasets, the join ancestors of both,
  and the date instances they require. Retained datasets keep every attribute, label and fact they
  have — pruning is dataset-level only.
- Per-domain filtering of the AI-context channels (`memoryItems`, parameters, agent personalities,
  AI knowledge) driven by `domains.yaml`: each domain's nested `ai` selection — ids plus the
  `memory_item_tags` rule — unioned with the manifest's `shared.ai`.
- Reachability-driven handling — not blanket emptying, and not filtering-out either — of
  `attributeHierarchies`, `exportDefinitions`, `dashboardPlugins`, `analyticalDashboardExtensions`
  and `filterContexts`: each is retained when a retained object references it, and each retained one
  pulls the attributes, labels, facts, datasets and join ancestors it needs into the LDM.
- A verification pass (`verify_child`) run on every generated child before it is written: every
  reference made by a retained object resolves inside that child, and every dataset in the child is
  accounted for by a retained object or by `ldm_include`. Failure aborts the whole run.
- A deterministic JSON writer/reader (`write_model_json` / `read_model_json` added to FEAT-001's
  `layout_io.py`) producing stable-sorted, reviewable, committed artifacts.
- `globalmart split [--domains-file config/domains.yaml] [--from layouts/workspaces/globalmart]
  [--out generated/workspaces] [--only <keys>] [--dry-run] [--check]` — a **local-file** writer, so
  it takes `--dry-run` per ADR 002's CLI convention, never `--apply`.
- `globalmart publish domains --target <profile> [--only <keys>] [--apply] [--no-backup]
  [--standalone-copy]` — sits beside `publish parent`, reads the committed JSON, and publishes each
  child through FEAT-002's `publish_workspace()` with `manifest.resolve_workspace_name(domain)` as
  `--workspace-name`.
- A split report (`SplitResult` / `DomainSplitResult`) printed by the CLI and asserted by tests:
  per-domain object counts, datasets retained vs pruned split into closure-reached and declared (e.g.
  `hr: 18 datasets (14 by closure, 4 declared)`), per-dataset used/total attribute and fact counts,
  which auxiliary objects each child retained, and coverage. Objects that are simply not reachable
  from a domain are not listed as losses; only genuinely unsatisfiable dependencies are, and those
  are errors rather than report lines.
- An offline test suite over committed fixtures, including the regression test for defect #2 (a child
  carrying a dataset it does not use must fail the build).

## Out of Scope

- Authoring or validating `domains.yaml` itself, including the coverage *input* rules and the
  prefix-based bootstrap of the initial file — that is FEAT-003. This feature consumes
  `load_domains()` and assumes validation has already passed; it re-asserts coverage of its own
  *output* only.
- Changing the parent. If a dashboard is mixed-domain or a metric is mis-scoped, the fix is in the
  parent tree or in `domains.yaml`, never in a generated file (STEERING: hand-editing a generated
  file is a defect).
- Datasource registration, org preflight, backups and the write calls — all reused verbatim from
  FEAT-002's `publish_workspace()`. This feature adds no new SDK call site.
- Column-level pruning of unused attributes/labels/facts *within* a retained dataset. **Decided and
  closed, not deferred:** pruning is dataset-level only, and a retained dataset keeps every column it
  has even when today's analytics touch a fraction of them. A label that looks unused may be a
  dataset's join grain or the target of another dataset's `reference`, and stripping it breaks the
  child in a way only discoverable at execution time — while keeping it is exactly the authoring
  headroom a child needs to grow new analytics. The report still prints per-dataset used/total
  attribute and fact counts, so if column-level pruning is ever reconsidered the decision is made on
  measured evidence rather than on intuition.
- Verifying that child visualizations actually execute against the warehouse — FEAT-006.
- Row data and warehouse loading — FEAT-005.
- Deleting child workspaces that were removed from `domains.yaml`. Removal from the manifest deletes
  the generated file; reaping the live workspace is a manual, user-initiated act.

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pruning is too aggressive: a metric's MAQL reaches a label whose dataset was not retained, and the child loads but cannot compute | High | High | `verify_child` re-walks every retained object's references against the pruned LDM *before* writing; any unresolvable reference aborts the entire run naming domain, object id and reference (AC #8). No child is ever written "optimistically" |
| Pruning is too timid: the join-ancestor closure (plus hierarchy/export pull-ins and declared `ldm_include`) drags in nearly the whole LDM and the children stay indistinguishable from the parent | Medium | High | The reverse assertion (AC #4) — every retained dataset must be accounted for by a retained object or by `ldm_include` — makes an unexplained dataset a build failure too. Per-domain `datasets_retained`, split into closure-reached and declared, is in the report and regression-pinned in a test, so a jump from 40 to 200 fails CI and the report says which of the two sources caused it |
| The reference direction on `dataset.references` is misread, so children carry dimensions but lose fact tables (or the reverse) | Medium | High | Direction is fixed by a fixture test built from a known parent subgraph (`fact_orders` → `dim_customer` → `dim_geo`) before the real run; the closure is forward-only along `references` and is asserted against a hand-computed expected set |
| MAQL reference extraction by regex misses a syntax form (`{metric/x}` vs `{label/x.granularity}` vs quoted ids) and a metric's dependency is silently lost | High | High | One shared, tested `MAQL_REF_RE` covering all five ref kinds plus granularity suffixes; a corpus test runs it over all 1075 parent metrics and asserts every extracted id resolves in the parent — an unresolvable extraction means the regex or the parent is wrong, and both are worth failing on |
| A mixed-domain dashboard drags a second domain's entire subgraph into a child, quietly de-narrowing it | Medium | Medium | Report prints, per domain, the datasets pulled in solely by a single dashboard; FEAT-003's manifest is the place to split or re-assign such a dashboard, and the report makes it visible rather than silent |
| Generated JSON is not byte-stable across SDK versions, so `git diff` fills with noise and stops being the review surface | Medium | Medium | Own the serializer (`json.dumps(deep_sort(...), sort_keys=True, indent=2)` + explicit list sorts), not the SDK's dump; `--check` in CI; SDK pinned by FEAT-001 |
| 12 publishes multiply FEAT-002's blast radius — one wrong `--target` replaces 12 workspaces | Low | High | ADR 002's `--apply` gate applies per child; a backup is taken before each PUT; the rehearsal prints all 12 diffs first; `--only` lets a single domain be published in isolation |
| AI-context filtering leaks another domain's memory items because the manifest selection is by id and ids drift | Medium | Medium | Every selected id must resolve in the parent or the run fails; a test asserts the pairwise intersection of the 12 children's AI-context id sets is empty unless the manifest declares the item shared |

## Dependencies

- **Depends on:** feat-001, feat-002 and feat-003. From feat-001: `read_tree`, `layout_io`, the
  `normalize` tokens and `counts`. From feat-002: `traversal.py`, `resolve.py`,
  `publish_workspace()`, `compare.py`, `preflight` and `backup`. From feat-003: `domains.yaml` plus
  `load_domains()` and the `DomainManifest` / `Domain` / `AiSelection` / `SharedSelection` /
  `UnassignedSelection` model, reached only through `by_key()`, `keys()`,
  `resolve_workspace_name()`, `unassigned_ids()`, `manifest.shared`, `domain.ai` and
  `domain.ldm_include` — this feature never parses the manifest, renders its name template, or
  re-implements its validation.
  **Note:** this feature's frontmatter carries `depends_on: []`, which contradicts FEAT-001 and
  FEAT-002 both declaring `enables: feat-004`. Frontmatter is CLI-owned and is left untouched here;
  it needs `depends_on: [feat-001, feat-002, feat-003]`.
- **Enables:** feat-006. The cold-rebuild verification executes the 12 children this feature emits
  and reads their `DomainSplitResult` counts and digests.
- **External:** `gooddata-python-sdk` (model classes only for generation; the publish path reuses
  FEAT-002's call sites), credentials per target profile for the publish step only.

## Related Research

- `publish_domain_workspaces.py` (predecessor): dashboard→viz→metric walk plus the transitive MAQL
  closure `re.findall(r"\{metric/([^}]+)\}", maql)` — the one part worth keeping verbatim, because
  without it the split fails at load with "metrics … cannot be found".
- Same script's `"ldm": model["ldm"]` — the full-LDM copy that this feature exists to replace, and
  `attributeHierarchies=[] / exportDefinitions=[] / dashboardPlugins=[] /
  analyticalDashboardExtensions=[]`, four silent drops.
- Same script's `json.dumps(model).replace('"globalmart-postgres"', ...)` — string replacement over
  serialized JSON, superseded by FEAT-002's `traversal.py` + `resolve.py` (STEERING § Coding
  Standards forbids the former outright).
- Measured on the 2026-06-25 export: 225 datasets = 214 table-backed (`dataSourceTableId`) + 11
  SQL-backed (`sql`), mutually exclusive; 1075 metrics; 384 visualization objects; 32 analytical
  dashboards; 2 date instances; 12 domains.
- ADR 001 fixes children as *derived, committed JSON* under `generated/workspaces/` and names the
  pruned LDM as a required property; it also records that the predecessor's closure logic is
  "retained as the starting point and hardened, not discarded".
- ADR 002 fixes the `--apply` gate and the `--dry-run` / `--apply` split; FEAT-002's breakdown
  already shapes the `publish` CLI group so `publish domains` sits beside `publish parent`, and
  already routes the child display name through `--workspace-name`.

## Open Questions

- ~~Should pruning also drop unused attributes, labels and facts *within* a retained dataset?~~
  **Resolved: no — dataset-level pruning only, and the question is closed rather than deferred.** A
  retained dataset keeps every attribute, label and fact it has. A label that looks unused may be a
  dataset's join grain or the target of another dataset's `reference`, and stripping it breaks the
  child only at execution time; keeping it is also precisely the headroom a child needs to author new
  analytics. The report prints per-dataset used/total attribute and fact counts so that a future
  reversal would be argued from evidence. See also `ldm_include`, which addresses the same need at
  dataset granularity.
- ~~How should an `attributeHierarchy` that spans two domains be handled — dropped from both
  children, retained in the majority owner, or retained where all its attributes are present?~~
  **Resolved: the question was framed backwards and is void.** A hierarchy is retained iff a retained
  visualization, dashboard or drill definition in that domain references it; once retained, every
  attribute it names, each attribute's dataset and that dataset's join ancestors are **pulled into**
  the pruned LDM. A hierarchy is never dropped for naming an attribute an earlier pass excluded — the
  attribute is included instead. A hierarchy no retained object references is simply not part of that
  domain, which is correct absence, not a drop. The same rule governs `exportDefinitions`,
  `dashboardPlugins`, `analyticalDashboardExtensions` and `filterContexts`, and it is the same rule
  the metric closure already follows. The only error case is a reference to an object that does not
  exist in the parent at all, which fails the whole run loudly (AC #8).
- Should a domain whose closure yields zero dashboards be an error or a warning? Proposed: an error —
  an empty domain workspace is always a manifest mistake.
- Does any child need `workspaceDataFilter` references restored? Assumed no: FEAT-001 resolved
  `WdfPolicy.DROP` as the default, so the parent tree carries none and children inherit that.
- Should `publish domains` hoist `ensure_data_source` and `check_organization` out of the per-child
  loop? Calling `publish_workspace()` 12 times performs 12 idempotent datasource upserts and 12 org
  checks. Correct but wasteful; proposed as a `publish.py` refactor only if the live run proves it
  slow.

## Outcome (2026-09-18)

Built and published. 265 tests, ruff and mypy clean, `split --check` wired into CI.

```
domain         datasets  metrics   viz  dash      published            idempotent
customer             24      186    36     3      globalmart-customer      yes
ecommerce            12       11    24     2      globalmart-ecommerce     yes
finance              16       65    36     3      globalmart-finance       yes
hr                   16       39    36     3      globalmart-hr            yes
inventory            19      185    24     2      globalmart-inventory     yes
loyalty              20       50    24     2      globalmart-loyalty       yes
marketing            20       49    36     3      globalmart-marketing     yes
product              17      109    36     3      globalmart-product       yes
real_estate          10       20    24     2      globalmart-real-estate   yes
risk                  9       33    36     3      globalmart-risk          yes
sales                37      346    36     3      globalmart-sales         yes
store_ops            18       63    36     3      globalmart-store-ops     yes

parent: 225 datasets, 1091 metrics    children prune 188-216 datasets each
```

**The defect this feature existed to kill is gone and asserted.** The predecessor wrote
`"ldm": model["ldm"]` into all twelve children, so every one carried all 225 datasets. The
narrowest child is now `risk` at 9 datasets, the widest `sales` at 37. All twelve were
published to `demo-cloud` and every one reads back `changed: False`, `diff: 0` against its
committed artifact.

### Seven things the implementation contradicted or added

1. **A live bug in FEAT-001/002, found by the fixture and fixed here.** All 214 table-backed
   datasets carried the literal source schema in `dataSourceTableId.path[0]`, which neither
   `normalize` nor `resolve` touched. Invisible so far because every target happens to use
   the schema `globalmart` — against a target with a different one, all 214 datasets would
   have pointed at a schema that does not exist there, and **the publish would have
   succeeded**, because the assertion looks for surviving placeholders and a hardcoded
   literal is not one. `traversal.iter_table_schema_slots` now covers it in both directions.
   This weakens the "portability proven rather than asserted" claim in FEAT-002's outcome:
   it was proven across two orgs *that share a schema name*.

2. **Sorting lists at emission corrupted the document.** The breakdown's determinism plan
   sorted every list. `dataSourceTableId.path` is `[schema, table]` positionally, so sorting
   put the schema second and the publish failed on an unresolved placeholder — and it would
   equally have reordered visualization `buckets`, `sorts` and date-instance `granularities`,
   none of which announce that they are ordered. Removed; determinism comes from sorted-id
   emission in the producer instead, held honest by `test_emission_is_byte_stable`.

3. **The breakdown's `MAQL_REF_RE` was wrong.** It excluded dots from bare ids
   (`[^}./]+`), which truncates every `{fact/fact_daily_store_sales.sales_amount}` in the
   parent. The dot is genuinely ambiguous — `transaction_date.month` is an id plus a
   granularity, `fact_orders.amount` is one id — and nothing in the syntax distinguishes
   them. The pattern now captures the whole dotted string and `EntityIndex.owner_of` resolves
   it against the date instances that actually exist, checked last so a real dotted id is
   never truncated.

4. **`cross_domain_tiles`, and `iter_entity_refs` including metrics.** A metric is an
   analytics object, not an LDM entity; routing one into the dataset resolver fails on an id
   that is perfectly valid. `LDM_KINDS` now excludes it explicitly.

5. **A new decision the spec did not anticipate: `--metric-policy`.** The parent has 1091
   metrics of which **747 sit on no visualization** — tagged L2–L5, a deliberately authored
   hierarchy. Pure closure drops all 747 from every child, taking the total across the twelve
   from 1156 to 351. For workspaces whose stated purpose is exercising AI search, routing and
   MCP tooling, that removes most of what is being searched. `dataset-fit` (now the default,
   user's decision) additionally keeps any metric whose entire transitive LDM dependency is
   already present, so it **cannot widen a child** — verified by
   `test_dataset_fit_adds_metrics_but_never_datasets`.

6. **Tests were writing backups into the working tree.** `publish_workspace(apply=True)`
   takes a backup, the `FakeSdk` serves a real model back, so publish tests wrote genuine
   YAML trees under `backups/` — including one under a `workspace_id_prefix` that exists only
   inside a test. An autouse fixture now points `GLOBALMART_BACKUP_DIR` at a temp directory.

7. **Publishing twelve children is slow, and the cost is backups, not the org checks.** The
   spec's open question proposed hoisting `ensure_data_source` and `check_organization` out of
   the loop. Those are not the problem: each child's pre-PUT backup is a full capture plus a
   YAML tree write, and for `sales` that is 37 datasets and 346 metrics. A full
   `publish domains --apply` runs into the tens of minutes, and one run wedged entirely and
   had to be killed. Worth a follow-up — the backup is the thing to make cheaper or
   parallel, and the wedge needs a timeout and a per-child progress line, since the command
   currently prints nothing until it finishes.

### Deviations from the plan, deliberate

- **No `tests/fixtures/expected_children/`.** Byte-for-byte golden children would pin SDK
  serialization rather than this feature's behaviour, and would need regenerating on every
  SDK bump. `test_emission_is_byte_stable` proves determinism directly, and
  `test_committed_children_match_a_fresh_split` pins the real twelve, which is the artifact
  anyone actually reviews.
- **`verify.py` collision resolved** as CONTRACT.md recommended: FEAT-004 keeps `verify.py`,
  FEAT-006 takes `verification.py`. Contract updated in the same commit.
- **ADR is `006-derived-children-and-the-pull-in-rule.md`** — `004` and `005` were taken.
