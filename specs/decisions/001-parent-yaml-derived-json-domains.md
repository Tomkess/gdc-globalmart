# 001 — Parent workspace as SDK YAML; domain workspaces derived as JSON

**Status:** Accepted
**Date:** 2026-09-18
**Context:** goal-01; all workspace authoring, splitting and publishing features

## Decision

The `globalmart` parent workspace is stored in the repo as the gooddata-python-sdk native
declarative layout tree (YAML, one file per object, written by `store_declarative_workspace`) and is
edited only in the repo — no UI authoring. The 12 domain workspaces are never authored; they are
derived from the parent by a splitter driven by an explicit `domains.yaml` manifest, written to
`generated/workspaces/globalmart-<domain>.json` as committed declarative JSON, and published from
there. Each child receives a pruned LDM containing only the datasets reachable from its retained
metrics and visualizations.

## Alternatives Considered

| Option | Pros | Cons |
|---|---|---|
| Chosen: parent as YAML in repo, children derived to JSON | Repo is source of truth; readable per-object diffs; children reproducible and reviewable; rebuild into any org | Loses UI authoring; splitter must be correct or children drift silently |
| Export live parent to JSON, patch, publish (status quo) | Fast UI authoring; already working | Live org is the truth; 2.9 MB unreviewable diffs; LLM-generated descriptions non-reproducible; stale snapshots |
| Hybrid: author in UI, pull back down into YAML on every change | Keeps UI authoring and code truth | Extra routine step that will be skipped; round-trip fidelity must be proven |
| Domain membership by `viz_<domain>_` id prefix (status quo) | Zero maintenance | Mixed-domain dashboards silently dropped, no coverage guarantee |
| Full LDM copied into every child (status quo) | Simple; any metric resolves | Every "domain" workspace still exposes all 225 datasets, which distorts AI search/routing evaluation |

## Consequences

- **Positive:** cold rebuild into a fresh org becomes possible; children are diffable artifacts under
  review; per-domain semantic narrowing makes eval results meaningful; publishing targets (demo
  cloud, local inference, any org) differ only by config.
- **Negative / trade-offs:** adding a dashboard means editing YAML, not dragging tiles; the splitter
  and the pruner become load-bearing code that needs tests; `domains.yaml` must be maintained as
  content grows.
- **Neutral:** the existing split logic in `publish_domain_workspaces.py` (dashboard → viz → metric
  transitive MAQL closure) is retained as the starting point and hardened, not discarded.

## Revisit Trigger

If YAML authoring proves too slow for the rate of content change, revisit the hybrid: keep code as
truth but add a proven round-trip (`store_declarative_workspace` → normalize → diff) so UI edits can
be pulled back safely.
