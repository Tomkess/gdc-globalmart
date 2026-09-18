# 005 — Explicit domain membership, enforced coverage, deny-by-default AI context

**Status:** Accepted
**Date:** 2026-09-18
**Context:** goal-01; FEAT-003 (the manifest) and FEAT-004 (the splitter that consumes it)

## Decision

Domain membership is declared in `config/domains.yaml` and read, never inferred. Three rules
follow from that, and they are the non-obvious ones:

1. **Membership is many-to-many.** A dashboard or visualization may belong to any number of
   domains. Coverage requires *at least* one, never exactly one.
2. **Coverage is enforced, and an exclusion costs a sentence.** Every dashboard,
   visualization and AI-context object in the parent must be assigned to a domain, declared
   under `shared:`, or listed under `unassigned:` **with a reason**. Anything else fails the
   command. `--strict` additionally rejects placeholder reasons (`TODO`, `TBD`, `n/a`, empty).
3. **AI context is deny-by-default.** A memory item, parameter, agent personality or
   knowledge object reaches a child only if that domain names it, a `memory_item_tags` rule
   matches it, or `shared.ai` declares it. Nothing is inherited implicitly.

The `viz_<domain>_` prefix convention survives in exactly one function,
`domain_bootstrap.bootstrap_manifest()`, which ran once to produce the first manifest. A test
(`tests/test_single_source_of_domains.py`) asserts the 12 keys and labels appear in only two
files: the manifest and that one seed module.

## Why

The predecessor decided membership at split time by testing
`viz_id.startswith(f"viz_{domain}_")`, and included a dashboard only when **every** tile
matched. A dashboard mixing Sales and Finance tiles therefore matched no domain and was
dropped — no error, no report, no count. The domain list itself lived in four places, so
adding a domain meant four edits and forgetting one was invisible.

Both failures share a shape: the system had an opinion it never stated. Replacing the
inference with a declaration only helps if the declaration is read exactly as written and
the gaps are loud, which is why strict parsing (an unknown key raises, naming its dotted
path) and enforced coverage are part of the same decision rather than nice-to-haves.

On AI context, STEERING names the failure mode explicitly: "cross-domain AI memory in a
child is also a defect". Leakage is worse than absence, so the default is nothing.

## Rejected alternatives

**Exclusive membership (one object, one domain).** Would force a mixed-domain dashboard
into a single home or into none — recreating the predecessor's drop-on-ambiguity behaviour
with a better error message. Children are separate workspaces, so a duplicated id never
collides; copying a dashboard into two children costs nothing and is what the content
actually means.

**Warn, don't fail, on uncovered objects.** A warning in a build nobody reads is how the
original bug survived. The cost of the strict rule is one sentence per deliberate exclusion;
the cost of the loose rule is not knowing what your children contain.

**Inherit all AI context into every child.** Simpler, and wrong in the one direction that
matters. It would satisfy "AI context travels" while violating "the splitter still filters
them per domain".

**`ldm_include` as coverage.** Rejected: it widens a child's LDM so new metrics can be
authored on tables today's dashboards do not touch. Letting it satisfy coverage would let a
domain claim objects it does not actually present. It is counted and reported separately,
and a domain listing only `ldm_include` entries fails validation.

## Consequences

- FEAT-004 reads the manifest only through `by_key()`, `keys()`, `resolve_workspace_name()`
  and `unassigned_ids()`, and must run `check_coverage` + `raise_for_report(strict=True)`
  before emitting anything, so a split cannot run against a stale manifest.
- A PR that adds a dashboard to the parent without assigning it to a domain fails CI,
  naming the dashboard.
- `CoverageReport.cross_domain_tiles` shows, before any split runs, which visualizations
  will be copied into more than one child.
- **Measured on the parent as committed 2026-09-18:** 32 dashboards, 384 visualizations,
  zero residue — every visualization is referenced by exactly one dashboard and every
  dashboard is single-domain. `multi_homed` is empty, `unassigned` is empty, and
  `shared` is empty. The many-to-many rule costs nothing today; it exists so that the first
  genuinely cross-domain dashboard is a one-line edit rather than a silent drop.
