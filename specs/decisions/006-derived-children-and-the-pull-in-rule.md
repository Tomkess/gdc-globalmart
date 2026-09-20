# 006 — Derived children: the pull-in rule, dataset-level pruning, and dataset-fit metrics

**Status:** Accepted
**Date:** 2026-09-18
**Context:** goal-01; FEAT-004 (the splitter), consumed by FEAT-006

## Decision

Each domain workspace is derived from the parent by transitive closure and committed as
declarative JSON. Four rules govern what a child contains:

1. **Reachability decides, and dependencies are pulled in.** An object travels into a child
   when something retained in that child references it. Once it travels, everything *it*
   needs travels too — attributes, their datasets, those datasets' join ancestors, date
   instances, other metrics. No object is ever excluded because a dependency did not
   independently survive an earlier pass.
2. **Pruning is dataset-level only.** A retained dataset keeps every attribute, label and
   fact it has.
3. **Both directions are verified before a byte is written**, and a failure aborts the whole
   run — all twelve domains, not just the offender.
4. **Metrics default to `dataset-fit`**: a metric also travels when its entire transitive LDM
   dependency already resolves inside the child.

## Why

The predecessor's `publish_domain_workspaces.py` got the metric closure right and everything
else wrong. It wrote `"ldm": model["ldm"]` into all twelve children, so an HR workspace still
exposed all 225 retail tables; it hardcoded `attributeHierarchies`, `exportDefinitions`,
`dashboardPlugins` and `analyticalDashboardExtensions` to `[]`, four silent drops; and it
decided membership by id prefix, dropping any mixed-domain dashboard without a word.

Those are one failure wearing four hats: the system had opinions it never stated. So the
rules above are paired with assertions that make each one falsifiable — the over-pruning
check would have caught the full-LDM copy, and `tests/test_verify.py` runs that exact
degenerate case and requires it to fail.

**On the pull-in rule specifically.** The original design question was framed as "what should
happen to an attribute hierarchy spanning two domains — drop it, or keep it where all its
attributes survive?" That framing is backwards and the question is void. A hierarchy is
retained iff something retained references it; its attributes' datasets are then pulled in as
a consequence. Filtering it *out* because the LDM had already been pruned would manufacture a
loss out of an ordering accident.

**On dataset-level pruning.** A label that looks unused may be a dataset's join grain or the
target of another dataset's `reference`. Stripping it breaks the child only at execution
time, in a dashboard tile. Keeping it is also the headroom a child needs to author new
analytics. The report prints per-dataset used/total counts so a reversal could be argued from
measurement.

**On `dataset-fit` metrics.** Measured on the parent: 1091 metrics, of which 344 sit on a
visualization and **747 sit on none** — tagged L2–L5, a deliberately authored hierarchy.
Under pure closure all 747 vanish from every child. For workspaces whose stated purpose is
exercising AI search, routing and MCP tooling, that removes most of what is being searched.
`dataset-fit` runs *after* the LDM is final, so it can only admit metrics whose tables are
already present and can never widen a child — free in the one dimension this feature exists
to control. Measured effect: 351 metrics across the twelve children becomes 1156, with every
child's dataset count unchanged.

## Rejected alternatives

**Column-level pruning within a retained dataset.** Rejected, not deferred — see above.

**Deciding auxiliary-object membership after the LDM is pruned.** Simpler to implement and
produces the bug: an object gets dropped for referencing something an earlier pass removed.
`tests/test_closure.py::test_a_hierarchy_pulls_its_datasets_in` is the assertion that
distinguishes the two designs.

**Sorting every list at emission time to force determinism.** Tried, and it corrupted the
document: `dataSourceTableId.path` is `[schema, table]` positionally, so sorting put the
schema second and the publish failed on an unresolved placeholder. It would equally have
reordered visualization `buckets`, `sorts` and date-instance `granularities`. Determinism
comes from the producer instead — sorted-id emission per channel — and
`test_emission_is_byte_stable` holds that honest.

**Per-child failure tolerance by default.** Rejected: twelve workspaces replaced against a
misconfigured target is twelve restores. The loop stops at the first failure and names what
was not attempted; `--keep-going` is opt-in and still exits non-zero.

## Consequences

- `generated/workspaces/*.json` are committed and reviewed as diffs; `split --check` runs in
  CI, so a hand-edited child or a parent change nobody re-split fails the PR.
- Measured on the parent as committed: children retain 9–37 datasets against the parent's
  225. The narrowest is `risk` at 9, the widest `sales` at 37.
- FEAT-004 adds **no new SDK call site**. `publish domains` is a loop over FEAT-002's
  unchanged `publish_workspace`, so preflight, the org-identity pin, backups and the
  `--apply` gate apply per child for free.
- A latent bug in FEAT-001/002 surfaced while building this and was fixed here: all 214
  table-backed datasets carried the literal source schema in `dataSourceTableId.path[0]`,
  which neither `normalize` nor `resolve` touched. It was invisible because every target so
  far uses the schema `globalmart`. Against a target with a different schema, every table
  would have pointed at a schema that does not exist there — and the publish would have
  succeeded, because the assertion looks for surviving placeholders and a hardcoded literal
  is not one. `traversal.iter_table_schema_slots` now covers it in both directions.
