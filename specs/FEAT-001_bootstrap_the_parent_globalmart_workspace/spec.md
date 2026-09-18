---
abandoned_at: null
abandoned_reason: null
appetite: m
blocked_at: null
blocked_by: null
confidence: high
created: '2026-09-18'
cycle: null
depends_on: []
enables:
- feat-002
- feat-003
- feat-004
goal: goal-01
id: feat-001
name: Bootstrap the parent globalmart workspace into the repo as a gooddata-python-sdk
  native YAML layout tree, with a normalizer that makes the dump deterministic and
  diffable
sources: []
status: done
tags: []
updated: '2026-09-18'
---

## Summary

Today the only complete definition of GlobalMart is the live `globalmart` workspace in
`petertomko.demo.cloud`, mirrored by a 2.9 MB exported JSON snapshot that is unreviewable in git and
already stale relative to the org. This feature performs the one-time capture that inverts that
relationship: pull the parent workspace down once via `get_declarative_workspace`, normalize it
into a deterministic, org-agnostic YAML tree committed to this repo, and from that point on treat
the repo as the source of truth. Everything else in goal-01 — publishing, splitting, verification —
reads from this tree, so its fidelity and determinism are load-bearing.

## Appetite

`m` — 1–2 weeks

## Acceptance Criteria

- [ ] Given credentials for `petertomko.demo.cloud`, when the bootstrap command is run, then the
      `globalmart` parent workspace is written to `layouts/workspaces/globalmart/` as a YAML tree
      with one file per object (datasets, date instances, metrics, visualization objects, dashboards,
      filter contexts).
- [ ] Given that tree, when it is loaded with
      `CatalogDeclarativeWorkspaceModel.load_from_disk(workspace_folder=...)`, then no organization
      id is required and no path segment contains one.
- [ ] Given the captured tree, when it is searched for `createdBy` or `modifiedBy`, then zero
      occurrences are found (the live export carries 420 and 1490 respectively).
- [ ] Given the captured tree, when dataset datasource references are inspected, then every one of
      the 225 `dataSourceId` values is the placeholder token, not `globalmart-motherduck`.
- [ ] Given the captured tree, when the 11 SQL-backed datasets are inspected, then every occurrence
      of the target's literal schema has been **replaced by** the `{{ datasource_schema }}`
      placeholder, and no literal schema identifier survives in any statement.
      *(Corrected 2026-09-18 after the first live capture: zero of the 11 SQL datasets carry the
      placeholder today — they carry a hardcoded `globalmart.` prefix, because the substitution was
      performed historically and written back to the live org. The normalizer therefore **introduces**
      the placeholder; it does not preserve one. A statement matching neither the placeholder nor the
      literal schema is an error, not a pass.)*
- [ ] Given a normalized tree and a second capture from the same unchanged workspace, when both are
      normalized, then `git diff` is empty (byte-stable: stable key order, stable list order, stable
      formatting).
- [ ] Given the captured tree, when object counts are compared to the live workspace, then they
      match exactly (expected order of magnitude: 225 datasets, 1075 metrics, 384 visualizations,
      32 dashboards).
- [ ] Given a round-trip (capture → normalize → load → compare against the live layout as fetched),
      then the two are semantically equal modulo the parameterized and stripped fields, and the
      comparison is asserted by a test rather than eyeballed.

## Scope

- A `bootstrap` command that captures one workspace from a configured host into the repo tree.
- A normalizer applied on capture: strip user references, replace datasource ids with a placeholder,
  preserve schema placeholders, drop or resolve the 4 `workspaceDataFilter` references, stable-sort
  every list and mapping, and write deterministic YAML.
- A neutral on-disk layout that does not use the SDK's `gooddata_layouts/<organization_id>/` path.
- A `normalize` entry point re-runnable over an existing tree (idempotent), so future captures and
  hand edits converge on the same form.
- Capturing the AI-context objects (`memoryItems`, parameters, agent personalities, AI knowledge)
  as first-class content. They must survive a cross-org publish intact — only user-scoped references
  inside them are scrubbed, never the content.
- Round-trip and determinism tests, using a committed fixture rather than a live host.
- A short `docs/` note recording which live workspace and host the tree was bootstrapped from,
  and on what date.

## Out of Scope

- Publishing the tree anywhere (FEAT-002).
- Domain membership or splitting (FEAT-003, FEAT-004).
- Row data and warehouse loading (FEAT-005).
- Repairing known content defects — the missing `fact_search_event` DDL behind
  `sql_channel_attribution`, duplicated descriptions, or eval-artifact metrics. Capture records
  reality; repairs are separate features so the diff that fixes them is reviewable.
- Regenerating object descriptions with an LLM. Descriptions are captured as text and versioned;
  they are never regenerated as part of a build.

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The live parent already contains eval artifacts and duplicated descriptions, so the capture enshrines them | High | Medium | Capture first, then clean in a follow-up feature with a reviewable diff; do not clean during capture |
| SDK YAML dump is not stable across versions or runs (dict ordering, float/str formatting) | Medium | High | Own the normalizer rather than trusting the dump; assert byte-stability in a test; pin the SDK version |
| Stripping `createdBy`/`modifiedBy` or the WDF refs loses information the target org needs | Low | Medium | Round-trip test publishes into a scratch workspace and compares; WDF handling decided explicitly, not silently |
| Capture is a one-off run against a host that later changes, and the tree silently diverges | Medium | Medium | Record source host/workspace/date; make `bootstrap` re-runnable and the normalized diff the review artifact |
| 2.9 MB of content becomes thousands of small YAML files, making review and merges awkward | High | Low | One file per object is the point; enforce stable naming so diffs are per-object and merges are local |
| Secrets or tokens embedded in datasource or LLM-provider objects get committed | Low | High | Normalizer allow-lists fields; a test asserts no credential-shaped keys survive |

## Dependencies

- **Depends on:** none (entry point of goal-01). External: read access to `petertomko.demo.cloud`,
  `gooddata-python-sdk` (`get_declarative_workspace` / `store_to_disk` / `load_from_disk` — never the
  org-scoped `store_declarative_workspace` wrapper).
- **Enables:** feat-002 (publish), feat-003 (domain manifest), feat-004 (splitter).

## Related Research

- `store_declarative_workspace(workspace_id, layout_root_path)` writes to
  `gooddata_layouts/<organization_id>/workspaces/<id>` — the org id is baked into the path
  (`catalog_service_base.py:34-35`). `CatalogDeclarativeWorkspaceModel.load_from_disk(workspace_folder=...)`
  takes an explicit folder and is the org-agnostic read path.
- The existing export in the predecessor repo carries 420 `createdBy`, 1490 `modifiedBy`, 225
  `dataSourceId` and 4 `workspaceDataFilter` occurrences; the LI publisher already had to strip user
  references to avoid 400s from the target org.
- Committed exports there were refreshed by `catalog_describe.py --export-layout` after LLM
  description passes, which is why the snapshot was never byte-reproducible.
- ADR 001 records why the parent is YAML-in-repo and children are derived JSON.

## Open Questions

- ~~Do the 4 `workspaceDataFilter` references need to survive into other orgs, or are they demo-org
  specific and safe to drop?~~ **Resolved 2026-09-18: no WDF policy is in use today, so they are
  demo-org residue — default `WdfPolicy.DROP`.** `KEEP` is still implemented and tested so that a
  future row-level-security design is a flag flip, not a rewrite. FEAT-002's counterpart is
  `put_declarative_workspace(..., standalone_copy=True)`.
- ~~Does the parent contain AI-context objects (`memoryItems`, parameters, agent personalities) that
  reference org- or user-scoped entities, and do they survive a cross-org publish?~~
  **Resolved 2026-09-18: yes — AI memory and the other AI-context channels must travel cross-org.**
  They are captured, versioned and republished as content; only user-scoped references inside them
  are scrubbed. A capture missing them is a failed capture (task 31a).
- ~~Are object descriptions in the live parent the cleaned version, or do they still carry the
  doubled text that the predecessor's cleanup script was written to repair?~~
  **Resolved 2026-09-18: clean.** Checked the 2026-06-25 export — 2713 descriptions, zero showing
  half-repeats or duplicated sentences. Re-verified on the real capture (task 33) because the export
  predates later live mutations.
- ~~Should the placeholder datasource token be a literal like `{{ datasource_id }}` or a structured
  field the publisher fills?~~ **Resolved 2026-09-18: the literal `{{ datasource_id }}`** — symmetric
  with the existing schema placeholder, one substitution mechanism for both, and an unresolved token
  is greppable in a published layout.
