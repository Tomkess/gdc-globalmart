---
abandoned_at: null
abandoned_reason: null
appetite: m
blocked_at: null
blocked_by: null
confidence: medium
created: '2026-09-20'
cycle: null
depends_on:
- feat-001
- feat-002
- feat-005
- feat-006
- feat-013
enables:
- feat-009
goal: goal-01
id: feat-012
name: 'Comprehensive multi-layer workspace data filter structure across GlobalMart:
  authored layers, compiled definitions and per-workspace assignments, coverage enforced
  and effect proven'
sources: []
status: draft
tags: []
updated: '2026-09-20'
---

## Summary

GlobalMart has no workspace data filters at all. Every workspace sees every row. That closes off
the entire class of things a data platform is normally asked to prove — tenant isolation, regional
scoping, "same dashboards, different data" — and it is the shape a customer with many clients
actually runs.

This feature makes WDF **authored, compiled, provisioned and tracked**, rather than clicked. One
YAML file declares the layers and who sees what. A compiler turns it into filter definitions,
per-workspace settings, dataset references and the child workspaces themselves. A GitHub Action
plans on pull request and applies on merge. Adding a client is four lines and a review.

The number of layers and the number of children are deliberately *not* design decisions. They are
rows in a file. The feature is the mechanism.

### Evidence — the live org already contains a working example, 2026-09-20

The same demo-cloud org runs a two-layer WDF on `demo_ecommerce`:

| Filter | Column | Defined on | Kind |
|---|---|---|---|
| `WDF__CLIENT_ID` | `wdf__client_id` | `demo_ecommerce` | synthetic |
| `WDF__PRODUCT_CATEGORY` | `product_category` | `demo_ecommerce` | natural |

Settings target the three child workspaces, each with its own `filterValues`. This confirms, without
guessing: layers stack, synthetic and natural columns both work, definitions live on the parent and
settings name the children.

### The structural constraint that shapes everything

`demo_ecommerce__clothing` returns **0 datasets and 0 date instances** of its own — a child
workspace inherits the parent's logical model wholesale and cannot carry its own.

GlobalMart's 12 domain workspaces have `parent: null` and *pruned* LDMs, which is the entire point
of FEAT-004 and ADR-006. Making them children would delete what the splitter exists to produce.

**Therefore WDF-filtered workspaces are a separate branch under `globalmart`, parallel to the
domains, not a property of them.** Domain pruning and data filtering stay orthogonal: the domains
answer "which subject area", the children answer "whose data". That separation is also what makes
the FEAT-009 claim honest — the same orchestrator routes across either axis, because they are
genuinely different axes.

### The shape

`config/wdf.yaml` is the only authored artifact:

```yaml
version: 1
parent: globalmart

layers:
  - id: tenant
    title: Client
    column: wdf__tenant_id
    data_type: STRING
    datasets: all
  - id: region
    title: Region
    column: wdf__region
    data_type: STRING
    datasets: all

children:
  globalmart-acme:
    title: ACME Corp
    tenant: [acme]
    region: [EMEA, AMER]
  globalmart-globex:
    title: Globex
    tenant: [globex]
    region: [APAC]
```

The compiler emits three artifact classes, all committed under `generated/wdf/` so the pull request
diff is the review surface:

1. Org-level `workspaceDataFilters` — one definition per layer, one setting per child.
2. `workspaceDataFilterReferences` on each participating dataset in the parent LDM.
3. Child workspace entities carrying `parent: globalmart`.

### What automation can and cannot reach

Adding a **child** is pure configuration. Adding a **layer** needs a physical column in the
warehouse, and GoodData will accept a filter naming a column that does not exist — it simply fails
at query time or filters nothing. That is precisely the failure mode FEAT-011 was created to fix,
so it gets a preflight rather than a hope.

| Change | Automated | Gate |
|---|---|---|
| new child | fully | assignment matrix complete for every layer |
| changed values | fully | plan diff reviewed in the pull request |
| new layer | config only | preflight fails until the column exists in the warehouse |
| removal | opt-in | explicit label or `allow_destructive: true` |

## Appetite

`m` — 1–2 weeks. The compiler and the gates are the bulk; the live example removes most of the
protocol risk. The work that supplies the columns is **not** in this estimate — it lives in FEAT-013.

## Acceptance Criteria

1. `config/wdf.yaml` is the single authored source for layers, children and assignments. No filter,
   setting, reference or child workspace is defined anywhere else.
2. `globalmart wdf build` compiles the YAML into committed artifacts under `generated/wdf/`, and
   `--check` exits non-zero if the artifacts would change — matching the existing gate convention.
3. The assignment matrix is complete and explicit: every child states a value set for every layer. A
   missing assignment fails the build. Nothing defaults to "sees everything."
4. `globalmart wdf plan` prints what would change against a live target — children to create,
   settings to add or change, dataset references to add, anything to be removed — and changes
   nothing.
5. `globalmart wdf apply` provisions against a target profile: creates missing child workspaces with
   `parent: globalmart`, writes the org-level filter definitions and settings, and writes dataset
   references into the parent LDM. Idempotent — a second run is a no-op.
6. **Column preflight.** Before applying, every layer's column is verified to exist in the warehouse
   tables it claims to cover. A layer naming a missing column hard-fails with the column and the
   affected tables named, and nothing is written.
7. **Coverage is enforced, deny-by-default.** A dataset that participates in a layer but cannot carry
   its column fails the build unless listed in an explicit `unfiltered:` allowlist with a stated
   reason. Coverage is computed per workspace, since the split prunes datasets per domain.
8. **Effect proof.** A check asserts that two children with different value sets return *different*
   results for the same visualization, and that the parent returns at least as much as any child. A
   filter that changes nothing fails, as does one that empties every child.
9. Removal is never implicit. A child or layer deleted from the YAML is reported by `plan` but not
   applied unless explicitly opted into.
10. A GitHub Action runs `wdf build --check` and `wdf plan` on any pull request touching
    `config/wdf.yaml` or the compiled artifacts, and posts the plan as a comment.
11. On merge to the default branch, the Action runs `wdf apply` against **every target profile whose
    token secret is present**. A profile with no secret is skipped and reported, not failed. Rebuild
    and load targets are opt-in per profile.
12. Seed content proves the mechanism end to end: two layers (`tenant`, `region`) and four tenant
    children, published and passing the effect proof.

## Scope

- `config/wdf.yaml` and its schema, including validation with useful errors.
- The compiler: YAML → filter definitions, settings, dataset references, child workspace entities.
- `globalmart wdf build [--check] | plan | apply` CLI verbs, following the existing publisher's
  target-profile and `--apply` conventions.
- The column preflight against the datasource.
- Coverage and effect gates, the latter extending FEAT-006's execution harness.
- The GitHub Action: plan on pull request, apply on merge, per-profile secret handling.
- Seed layers and four children.
- Documentation of the authoring loop: add a client, open a pull request, read the plan, merge.

## Out of Scope

- **Emitting the `wdf__*` columns into the data.** That belongs to FEAT-007's generator, which owns
  the 215 tables and the determinism guarantee. This feature consumes the columns and refuses to
  apply without them (AC 6). Stamping them rewrites the committed archive that ADR-007 treats as the
  source of truth, which is a decision about the data artifact, not about filtering.
- **Filtering the 12 domain workspaces.** Structurally impossible without making them children and
  losing their pruned LDMs. Explicitly rejected above, not deferred.
- **User data filters.** A different mechanism with different semantics (per-user rather than
  per-workspace). If per-user scoping is wanted for the FEAT-009 auth story, it is its own feature.
- **Real tenant semantics.** There is no customer provisioning process behind this; the Action *is*
  the process. Modelling a real onboarding flow is out of scope, and the seed tenants are fictional.
- Permissions, users and groups on the child workspaces. Provisioning creates workspaces, not
  identities.

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A layer names a column that does not exist; GoodData accepts it and silently filters nothing | High without a gate | High | The column preflight (AC 6) is the whole mitigation. This is the FEAT-011 failure repeating in a new place, and structural checks alone will not catch it |
| An apply against every profile has a wide blast radius, including load and rebuild targets | Medium | High | Rebuild and load targets opt in per profile; secrets absent means skipped; `plan` output is reviewed in the pull request before merge |
| Removing a child from the YAML deletes a live workspace and its data access | Low with the gate, High without | High | Removal is never implicit (AC 9); it needs an explicit opt-in on the pull request |
| Children inherit the parent LDM, so a parent LDM change silently reaches every tenant | Medium | Medium | Inherent to the mechanism and not worth fighting; the effect proof runs across children so a breaking change surfaces as a failing gate |
| Four extra workspaces slow the verification harness | Medium | Low | Children carry no model of their own; measure once and cap concurrency if needed |
| The compiled artifacts drift from the live org through manual UI edits | Medium | Medium | `plan` is a drift detector by construction; run it on a schedule as well as on pull requests |
| Assignment matrix becomes unwieldy as layers and children grow | Low near term | Medium | Completeness is enforced rather than inferred (AC 3), so growth is visible and reviewed rather than quietly incoherent |

## Dependencies

- **Depends on:** feat-013 — the archive must carry `wdf__tenant_id` and `wdf__region` across the
  tables the layers claim, and be reloaded, before any apply can pass preflight. Also feat-001 (the parent layout that carries dataset references), feat-002 (the
  target-profile publish conventions this CLI follows), feat-005 (the warehouse load path the
  preflight inspects) and feat-006 (the execution harness the effect proof extends).
- **Enables:** feat-009 — supplies the `tenants` scenario for the orchestrator registry, so the
  AIS-55 demo can show that the same orchestrator crosses either axis with only the registry
  descriptions changing.

## Related Research

- `CatalogDeclarativeWorkspaceDataFilter` = `{id, title, column_name, workspace?, settings[]}`;
  `CatalogDeclarativeWorkspaceDataFilterSetting` = `{id, title, filter_values[], workspace}`;
  `CatalogDeclarativeWorkspaceDataFilterReferences` = `{filter_id, filter_column,
  filter_column_data_type}` attached per dataset. Verified in the pinned SDK, 2026-09-20.
- Live `GET /api/v1/layout/workspaceDataFilters` on demo-cloud returns the `demo_ecommerce` example
  described above, plus an unrelated `product_id` filter on workspace
  `671c2de9839449218e483d57f798d15f`.
- `filter_column` is declared per dataset, so datasets may carry the same filter under different
  physical column names. Useful for the natural-column case; the synthetic layers will not need it.
- Column reach across the 215 committed tables: no column appears in more than 40. `customer_id` 40,
  `store_id` 39, `product_id` 32, `country_id` 8, `region_id` 5. This is why both seed layers are
  synthetic — there is no natural GlobalMart column with the reach to be a credible tenant axis.
- All 13 existing GlobalMart workspaces have `parent: null` today.

## Open Questions

- What are the seed tenants? Four fictional clients is the plan, but whether they should resemble
  Infobip's shape (four channels of one business) or be four plainly separate companies changes how
  the FEAT-009 demo reads.
- Should `region` be the second layer at all, or is one layer plus a second added later a better way
  to prove the "adding a layer" path actually works in anger? Shipping with one layer and adding the
  second through the real pull-request flow would exercise the mechanism rather than assert it.
- Does the effect proof belong in FEAT-006's harness or stand alone? Same question FEAT-011 raises;
  the two should be answered together so there is one filter-effect mechanism, not two.
- How should a profile without a token secret be reported so it is noticed rather than ignored? A
  skipped profile that nobody sees is drift waiting to happen.
- Does anything need to happen for the datasource to expose the new columns — a scan, a cache
  invalidation — or is a layout push sufficient once the warehouse has them? Worth establishing
  before the first apply rather than debugging it live.
