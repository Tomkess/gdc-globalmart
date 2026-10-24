# Project Steering

Guidance for AI agents working in this project. Read by `/spec`, `/breakdown`, `/tasks`, and `/plan`
before producing any output — treat these as hard constraints, not suggestions.

**Interfaces live in [`CONTRACT.md`](CONTRACT.md), not here.** Module ownership, shared types
(`TargetProfile`, `DomainManifest`, `CanonicalDataSource`), the CLI surface and the on-disk paths
are pinned there and are binding. Read it instead of reading other features' `spec.md` /
`breakdown.md` to find out what something is called. This file holds *principles*; that file holds
*names*.

---

## Architecture Constraints

- **The repo is the source of truth, never a live org.** Nothing may require reading a live
  GoodData workspace in order to rebuild GlobalMart.
- **Parent workspace** is stored as the gooddata-python-sdk native layout tree (YAML, one file per
  object) under `gd_data_product/globalmart/`, in exactly the bytes gdcloud's `gd-store` and
  `gd-format-yaml` write — a neutral path with no org id (ADR 011 Stage B). Reads go through
  `CatalogDeclarativeWorkspaceModel.load_from_disk(workspace_folder=...)` and writes through
  `layout_io.write_tree` (the SDK's `store_to_disk` plus gdcloud's normalizers), never through
  `store_declarative_workspace` / `load_declarative_workspace`, which route through
  `layout_organization_folder()` and bake the org id into the path.
- **Domain workspaces are derived, never authored.** They are generated from the parent by the
  splitter and committed as declarative JSON under `generated/workspaces/`. Hand-editing a
  generated file is a defect; fix the parent or `domains.yaml` and regenerate.
- **Domain workspaces are local-only (ADR 011).** They stay derived, committed and gated, but no
  release path deploys them: they are published on demand (`publish domains --apply`) and never
  spend a slot of the orgs' workspace cap by default.
- **gdcloud releases the parent, and only the parent (ADR 011).** `gd_data_product/globalmart/` is
  the parent's only authoring tree: edit it, or `gd-store` into it from a dev workspace (gdcloud
  workflows 1/2a/2b). `config.yml` declares exactly one data product.
- **This repo never releases or snapshots org-level objects, and never reads or writes
  organization-level knowledge documents.** `automation.org_release` and
  `automation.organization_snapshot` stay `false`, and every target's `knowledge_scope` is
  `workspaces`; both orgs are shared, and a separate org repo owns agents, themes, org-level AI
  Knowledge and the like (gd-ecommerce-demo ADR 002, ADR 011). The `org_scope` gd-ci check enforces it.
- **Commit what a human reviews, not what a machine consumes.** `generated/workspaces/*.json` is
  committed because its diffs carry meaning. Warehouse rows are not: they are fetched from a
  project-owned archive and verified against the committed `data/archive-manifest.json`, with the
  local cache gitignored. See ADR 003.
- **The repo, not the UI, is where a change lands.** A change is either a YAML edit or a dev-workspace
  build brought back by `gd-store`; either way it reaches an org only as a reviewed, merged PR.
  Capturing from a shared or released workspace is not a routine step.
- **Domain membership is explicit** — declared in `domains.yaml`, not inferred from object-id
  naming conventions. Prefix conventions may only be used to bootstrap that file once.
- **Every child workspace gets a pruned LDM** — only the datasets that domain actually needs: those
  reachable from its retained analytics (metrics, visualizations, dashboards, filter contexts,
  attribute hierarchies, export definitions and every other object retained in that child), those
  named in the domain's declared `ldm_include`, and the join ancestors of all of the above. An object
  that travels into a child brings everything it requires with it — dependencies are pulled in, never
  filtered out. Pruning is **dataset-level only**: a retained dataset keeps all of its attributes,
  labels and facts. Never ship the full LDM to a child.
- **Coverage is enforced**: every dashboard and visualization in the parent must land in at least
  one domain, or the split fails loudly.
- **Everything is parameterized** by host, org, datasource id and warehouse schema. No hardcoded
  host, org, datasource or workspace id anywhere except `domains.yaml` and config. A code-level
  *default* matching the naming convention (e.g. `parent_workspace_id = "globalmart"`) is allowed,
  provided the effective value always resolves through config and can be overridden there.
- **Publishing is idempotent** — re-running any publish or load step must converge, not duplicate.
- **Writes to a live org are opt-in.** Any command that can write is a read-only rehearsal by
  default and performs writes only under an explicit `--apply`, with a backup taken immediately
  before a destructive call. See ADR 002. CLI convention: `--apply` gates remote writes;
  `--dry-run` belongs only to commands whose writes are local files. No command has both.

## Portability Contract (org-agnostic)

The committed layout must carry no trace of the org it was captured from
(`petertomko.demo.cloud` today). Concretely:

- **Layout path carries no org id.** `store_declarative_workspace` writes to
  `gooddata_layouts/<organization_id>/...` (`catalog_service_base.py:34-35`). The repo stores the
  parent under a neutral folder and loads it with
  `CatalogDeclarativeWorkspaceModel.load_from_disk(workspace_folder=...)`, which takes an explicit
  path and never consults the org id.
- **No user references.** `createdBy` / `modifiedBy` never reach the tree — `gd-store` captures
  with activity info excluded, and every publish refuses a model that carries them — a foreign user
  id makes the target org reject the layout. (A raw export carries 420 + 1490 of them.)
- **Datasource is a parameter.** The tree carries one canonical data source id
  (`gd_data_product/config.env.yml`); all 225 dataset `dataSourceId` references are rewritten to the
  target's at publish time by structured traversal, not by string replacement, and a no-op when they
  match.
- **Schema is a parameter.** Likewise the canonical schema: every table path's schema and every SQL
  dataset's `<schema>.` prefix is rewritten to the target's, never stripped. A publish fails if any
  other data source id or schema, or any leftover `{{ … }}` placeholder, survives.
- **Workspace data filters** (4 present) are resolved or explicitly removed per target, since they
  reference org-scoped filter ids.
- **AI context travels.** `memoryItems`, parameters, agent personalities and AI knowledge are
  first-class versioned content and must survive a cross-org publish intact. Only user-scoped
  references *inside* them are scrubbed. A capture or publish that drops them is a defect. (The
  splitter still filters them per domain — cross-domain AI memory in a child is also a defect.)
- **Config, not code.** Host, token, org, datasource id and schema come from environment/config
  profiles — one profile per target (demo cloud, local inference, a fresh org). Adding a target is
  a config entry, never a code change.
- **Acceptance:** publishing the same repo state into two different orgs yields workspaces whose
  layouts are identical except for the parameterized values.

## Coding Standards

- Python 3.14+ (gdcloud's floor), `uv` as package manager, type hints on public functions. `ruff check`
  and `ruff format` both gate PRs.
- Prefer `gooddata-python-sdk` APIs over raw REST. Raw REST only where the SDK has no coverage, and
  the gap must be noted in a comment.
- Mutations of object references (datasource ids, schema names) are structured traversals, never
  string replacement over serialized JSON.
- Generated artifacts are deterministic and stable-sorted so git diffs are reviewable.

## Naming Conventions

- Parent workspace id: `globalmart`. Child ids: `globalmart-<domain>` (kebab-case).
- Release workspace ids (gdcloud): `globalmart_dev`, `globalmart_test`, `globalmart_preprod`,
  `globalmart_master` (prod). Data source on the release orgs: `gdc_ds_globalmart_motherduck`.
- Domain keys in `domains.yaml`: snake_case. Generated files: `generated/workspaces/globalmart-<domain>.json`.
- Feature IDs: `feat-NNN` in frontmatter, `FEAT-NNN` in display.

## Domain Glossary

- **parent** = the single `globalmart` workspace holding the whole model; the editing surface
  (`gd_data_product/globalmart/`).
- **domain workspace** / **child** = one of the derived per-domain workspaces.
- **split** = the deterministic derivation of children from the parent.
- **prune** = removing LDM datasets a child neither reaches nor declares; whole datasets only, never
  individual columns.
- **closure** = transitive expansion of references (dashboard → viz → metric → metric → dataset).
- **LI** = local inference host, one of several publish targets.

## AI Behavior

- Plan before building: stay in `/spec` → `/breakdown` → `/tasks`. Do not execute against a live
  GoodData host unless the user explicitly asks for that run.
- Never treat supplied credentials, hosts or MCP URLs as a cue to run something live.
- Surface a decision rather than guess; record non-obvious choices as an ADR in `specs/decisions/`.
- Tasks sized at 1–4 hours each.
