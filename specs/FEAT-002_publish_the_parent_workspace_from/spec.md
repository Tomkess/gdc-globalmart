---
abandoned_at: null
abandoned_reason: null
appetite: s
blocked_at: null
blocked_by: null
confidence: high
created: '2026-09-18'
cycle: null
depends_on:
- feat-001
enables:
- feat-004
- feat-006
goal: goal-01
id: feat-002
name: Publish the parent workspace from the repo YAML layout into any host/org/datasource,
  parameterized and idempotent, with no hardcoded identifiers
sources: []
status: in-progress
tags: []
updated: '2026-09-18'
---

## Summary

With the parent captured as a normalized YAML tree (FEAT-001), this feature makes it publishable
into *any* GoodData org the user controls — `petertomko.demo.cloud`, the local-inference host, or a
freshly created empty org — with the target expressed entirely as configuration. (The org itself is
provisioned outside this repo; publishing assumes it exists and that the token can reach it.) It
registers or reuses the datasource, creates or updates the workspace, resolves every placeholder
(datasource id, schema) by structured traversal, and applies the layout idempotently. This is the step that turns
"a repo describing GlobalMart" into "GlobalMart, anywhere", and it is the precondition for the
splitter publishing children the same way.

## Appetite

`s` — 1–3 days

## Acceptance Criteria

- [ ] Given a target profile naming host, token env var, datasource id, warehouse type and schema,
      when `publish parent --target <profile> --apply` runs, then the `globalmart` workspace exists
      in that org with the full LDM and analytics from the repo tree.
- [ ] Given the same command **without** `--apply`, when it runs, then it performs every read,
      resolution and assertion, prints the diff it would apply, and writes nothing to the host —
      `--apply` is the only way to reach a write.
- [ ] Given the same command run twice against the same target, when the second run completes, then
      the resulting layout is byte-identical to the first (idempotent; no duplicated or orphaned
      objects).
- [ ] Given a target whose datasource id differs from the source's, when publishing, then all 225
      dataset datasource references point at the configured id — verified by traversing the loaded
      model, not by string matching.
- [ ] Given SQL-backed datasets carrying `{{ datasource_schema }}`, when publishing, then the
      placeholder is substituted with the target's schema and no templated placeholder survives into
      the published workspace.
- [ ] Given two different target orgs, when the same repo state is published to both and each
      resulting layout is fetched and normalized, then the two normalizations are identical except
      for the parameterized values (host, org, datasource id, schema).
- [ ] Given a target profile that omits a required value, when publishing, then the command fails
      before contacting the host, naming the missing key.
- [ ] Given a target org where the datasource does not yet exist, when publishing, then it is created
      from the profile; given one where it exists, then it is updated rather than duplicated.
- [ ] Given a grep of the implementation, when searching for host names, org ids, workspace ids or
      datasource ids, then none appear outside configuration files.

## Scope

- A target-profile config format (one profile per org/warehouse combination) with secrets resolved
  from environment variables, never stored in the repo.
- Datasource registration/update via `catalog_data_source`, supporting at minimum MotherDuck and
  Postgres.
- Workspace create-or-update plus `put_declarative_workspace` from the repo tree.
- A placeholder resolution pass performed on the loaded model by structured traversal of dataset
  datasource and SQL references.
- A read-only rehearsal as the **default** behaviour — resolves everything, asserts, and reports what
  would change without writing. `--apply` is the only path to a write (ADR 002). There is no
  `--dry-run` flag on this command; the CLI convention is `--apply` for anything that writes to a
  live org, `--dry-run` for commands that only write local files (e.g. FEAT-001's `bootstrap`).
- Tests over the resolution pass against a committed fixture (no live host required).

## Out of Scope

- Publishing the 12 domain workspaces (FEAT-004 — it reuses this publisher).
- Loading row data into the warehouse (FEAT-005). Publishing a workspace against an empty warehouse
  must succeed; only execution of visualizations will fail, which FEAT-006 reports.
- Verifying that visualizations actually compute (FEAT-006).
- Org-level provisioning: creating orgs, users, groups, permissions, or LLM providers.
- Migrating any existing content already living in `petertomko.demo.cloud` — that org is treated as
  just another target, with the repo overwriting it.

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `put_declarative_workspace` is destructive — it replaces workspace content wholesale | High | High | Writes require an explicit `--apply`; without it the command is a full read-only rehearsal that prints the diff. Mandatory backup of the target's current layout immediately before the PUT. Report carries `digest_before`/`changed` so an unexpected overwrite is visible. Documented that targets are owned by the repo |
| Predecessor patched datasource references by string-replacing a literal that did not even appear in the file, leaving stale references silently | High | High | Structured traversal with an assertion that zero unresolved placeholders and zero foreign datasource ids remain post-resolution |
| Cross-org publish rejected (HTTP 400) because of residual user or org-scoped references | Medium | Medium | FEAT-001's normalizer strips them; this feature asserts absence before the call and surfaces the server error body verbatim |
| Warehouse-specific datasource objects diverge (MotherDuck vs Postgres attributes) | Medium | Medium | Profile declares warehouse type; one small adapter per type, with the unsupported types failing loudly rather than silently |
| A token with write access to the wrong org publishes over real content | Low | High | Profile pins host *and* expected org id; publisher verifies the connected org matches before writing |

## Dependencies

- **Depends on:** feat-001 (normalized, placeholder-bearing parent tree).
- **Enables:** feat-004 (children publish through the same path), feat-006 (needs a published target
  to verify).
- **External:** `gooddata-python-sdk` (`catalog_data_source`, `catalog_workspace`), credentials per
  target profile.

## Related Research

- Predecessor publisher registered the datasource with `CatalogDataSourceMotherDuck` +
  `TokenCredentials` and applied the layout with `put_declarative_workspace`, but rewrote the
  datasource by `raw.replace('"globalmart-postgres"', ...)` on serialized JSON — a no-op for the
  main layout, which carried `globalmart-motherduck`. This is the specific failure mode to design
  out.
- Its LI publisher read layouts from the live demo org rather than from the repo, so with the demo
  org unavailable there was no publish path at all. The repo must be the only input here.
- `{{ datasource_schema }}` must be substituted, not stripped — stripping it was a known publishing
  defect in the predecessor.
- `put_declarative_workspace(..., standalone_copy=True)` removes workspace-data-filter references
  from the LDM, relevant if FEAT-001 decides to keep them in the tree.
- STEERING.md "Portability Contract" enumerates the full org-coupling checklist this feature must
  satisfy.

## Open Questions

All four are resolved — by the breakdown and by ADR 002. Kept here with their answers so the
reasoning is not buried.

- ~~Drift detection, or always overwrite?~~ **Always overwrite, but never by default and never
  blind:** writes are gated on `--apply`, a backup runs immediately before the PUT, and
  `PublishResult.digest_before` / `changed` surface drift in the report. The default rehearsal prints
  the diff before any write is possible.
- ~~Where do backups live?~~ **Gitignored local `backups/<target>/<workspace>/<UTC timestamp>/`**,
  written as a YAML tree by `write_tree()` so a rollback is just
  `globalmart publish parent --from backups/... --apply`. No object storage.
- ~~One profile per (org × warehouse), or a workspace-id prefix too?~~ **Both.**
  `workspace_id_prefix` (default `""`) is a profile field, so several GlobalMart copies coexist in
  one org for A/B eval runs without a second profile.
- ~~Does local inference need a different credential mechanism?~~ **Yes, and it is already a profile
  field:** `warehouse_type: postgres` selects `BasicCredentials` (`datasource_username` +
  `datasource_secret_env`) against MotherDuck's `TokenCredentials`. Adding a third warehouse is an
  adapter, not a redesign.
- **Decided 2026-09-18, not originally asked:** the workspace display name travels with the content,
  not the target — `PARENT_WORKSPACE_NAME = "GlobalMart"` in `publish.py`, overridable per
  invocation with `--workspace-name`, and supplied by `domains.yaml` for each child in FEAT-004.
  `TargetProfile` gains no name field, so the same GlobalMart carries the same name in every org.
