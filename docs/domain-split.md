# The domain split

One editing surface — the parent `globalmart` workspace — and twelve children derived from
it. You never edit a child. If something is wrong in one, the fix is in the parent tree or
in `config/domains.yaml`, and then you re-split.

```bash
globalmart split                       # write generated/workspaces/*.json
globalmart split --dry-run             # report only
globalmart split --check               # CI gate: committed children match a fresh split
globalmart split --only sales,hr       # one or two domains
globalmart publish domains --target demo-cloud          # rehearsal
globalmart publish domains --target demo-cloud --apply  # write to the org
```

Generated files live in `generated/workspaces/globalmart-<domain>.json` and are committed,
because the `git diff` is the review surface (ADR 001). **Hand-editing one is a defect** —
`split --check` fails the build and names the file.

## What a child contains

The manifest names a domain's dashboards and visualizations. Everything else is implied, and
the splitter computes the implication to fixpoint:

```
dashboards  ->  visualizations  ->  metrics  ->  metrics (transitively, via MAQL)
                     |                  |
                     +------------------+--> LDM entities -> datasets -> join ancestors
                                                                      -> date instances
```

**One rule governs all of it: reachability decides what travels, and whatever travels pulls
its dependencies in with it.** An attribute hierarchy referenced by a retained visualization
is retained, and the datasets of every attribute it names come with it — including ones no
visualization in that domain touches. Nothing is ever dropped because a dependency did not
independently survive an earlier pass; the dependency is included instead.

The corollary matters as much: an object that nothing in a domain references is simply not
part of that domain. That is correct absence, not a loss, and nothing reports it as one. The
only failure is a reference to something that does not exist **in the parent** — which stops
the entire run, for every domain, and writes nothing.

### The six stages

1. **Seed** — the domain's dashboards and visualizations, **unioned with `shared:`** (shared
   objects belong in every child, so they are part of the seed, not a later merge), plus
   `ldm_include` as declared dataset seeds.
2. **Dashboards** → visualizations, filter contexts, plugins, drill-target dashboards.
3. **Visualizations** → metrics and LDM entities, including inline MAQL.
4. **Metric MAQL closure** — a worklist, so a metric referencing a metric referencing a
   metric all travel. This is the one piece kept from the predecessor; without it a child
   fails to load with *"metrics … cannot be found"*.
5. **Auxiliary objects** — hierarchies, export definitions, plugins, dashboard extensions —
   retained by reachability, then feeding their own references back into the closure.
   Deciding this *before* datasets are resolved is what makes the pull-in rule work.
6. **Entities → datasets → join ancestors → date instances.**

Stages 2–5 loop together: a retained export definition can name a dashboard that pulls in new
visualizations that pull in new metrics.

### Join direction

`dataset.references` is followed **forward only**. A dataset's references point at the
datasets it joins *to* — its dimensions — so a retained fact table drags its dimensions in,
while a retained dimension never drags in the facts pointing at it. That asymmetry is the
narrowing. Backwards, children are either the whole parent again or missing every dimension,
and both look plausible in a summary line, which is why `tests/test_prune.py` asserts the
`fact_orders → dim_customer → dim_geo` chain literally in both directions.

### Pruning is dataset-level only

A retained dataset keeps **every** attribute, label and fact it has. A label that looks
unused may be a join grain or another dataset's reference target, and stripping it breaks the
child only at execution time — while keeping it is exactly the headroom a child needs to grow
new analytics. The report prints per-dataset used/total counts so a future proposal to prune
columns can be argued from measurement.

### Metrics: `--metric-policy`

| Policy | Rule |
|---|---|
| `dataset-fit` (default) | Also keep any metric whose **entire** transitive LDM dependency already resolves inside the child. |
| `reachable` | Pure closure: only metrics a retained visualization measures, or another retained metric names. |

The parent has 1091 metrics; **344 sit on a visualization and 747 sit on none** — tagged
L2–L5, a deliberately authored metric hierarchy. Under `reachable` all 747 vanish from every
child, which for workspaces built to exercise AI search, routing and MCP tooling removes most
of what is being searched. `dataset-fit` cannot widen the LDM — a metric qualifies only
because every table it needs is already there — so it is free in the one dimension this
feature exists to control.

## Verification, before anything is written

Every child passes a two-directional gate:

- **Under-pruning** — every reference a retained object makes resolves inside the child.
- **Over-pruning** — every dataset in the child's LDM is explained: reached by the closure,
  named in `ldm_include`, or a join ancestor of one of those.

Either violation aborts the whole run. The over-pruning check is the predecessor's defect
stated as an assertion: it wrote `"ldm": model["ldm"]` into all twelve children, so every one
carried all 225 datasets. `tests/test_verify.py` runs that degenerate case and requires it to
fail.

## Reading the report

```
hr               16 datasets (16 by closure, 0 declared)     39 metrics    36 viz    3 dash    0 ai
```

- **datasets** — retained, split into what the closure reached and what `ldm_include`
  declared, so declared widening stays visible and cannot creep.
- **ai** — memory items, parameters, agents and knowledge that reached this child. AI context
  is deny-by-default: an object travels only if the domain names it, a `memory_item_tags`
  rule matches, or `shared.ai` declares it. A zero column is visible rather than comfortable.

There is no `dropped_*` column anywhere, deliberately. An object nothing references is not a
loss, and an unsatisfiable dependency is an error rather than a report line.

## Placeholders

Generated children carry `{{ datasource_id }}` and `{{ datasource_schema }}` verbatim.
Substitution happens at publish time, in `resolve.py`, per target. No code path in the split
does string replacement over serialized JSON — that was the predecessor's method, and it
replaced a literal that was not in the file, silently doing nothing.

## Publishing

`publish domains` is a loop over FEAT-002's unchanged `publish_workspace`, so every guard
comes along per child: preflight, the org-identity pin, the datasource upsert, placeholder
resolution, a backup before each write, and the `--apply` gate. The workspace display name is
`manifest.resolve_workspace_name(domain)` — the per-domain override if there is one,
otherwise `workspace_name_template` rendered with the label. Nothing concatenates that string
by hand.

A failure stops the loop and names the domains not attempted, because twelve workspaces
replaced against a misconfigured target is twelve restores. `--keep-going` continues anyway
and still exits non-zero.
