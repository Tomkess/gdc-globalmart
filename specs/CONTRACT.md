# Shared Interface Contract — gdc-globalmart

The single source of truth for interfaces crossing feature boundaries: package layout, module
ownership, shared types, CLI surface, and on-disk paths.

**Why this file exists.** Before it, every planning agent was handed upstream features' full
`spec.md` + `breakdown.md` + `tasks.md` so it would agree on names — tens of thousands of tokens
per agent, re-sent on every turn of its loop, and still drifting (FEAT-003/004 needed ten
divergences reconciled by hand). Pass **this file's path** to a planning or build agent instead of
upstream documents. An agent needs an upstream `breakdown.md` only when it is changing that
feature's internals.

**Rules.** Anything named here is binding — implement it as written, do not re-derive it. If a
feature needs a change to a shared name or signature, change it *here first*, in the same commit,
and say so in that feature's breakdown. A module is owned by exactly one feature; other features
import from it and never redefine its types.

---

## Package layout

Python package under `src/globalmart/`, flat except the `data/` submodule. One module, one concern.

| Module | Owner | Concern |
|---|---|---|
| `config.py` | FEAT-001 (+002, +005) | `TargetProfile`, `WarehouseType`, `load_profile`, `validate_for_publish` |
| `sdk_client.py` | FEAT-001 | `make_sdk(profile) -> GoodDataSdk` — the only place touching credentials |
| `capture.py` | FEAT-001 | `capture_workspace(sdk, workspace_id) -> CatalogDeclarativeWorkspaceModel` |
| `normalize.py` | FEAT-001 | Six-pass in-memory scrub; owns the placeholder tokens |
| `layout_io.py` | FEAT-001 (+004) | `write_tree` / `read_tree` (YAML), plus the JSON side for children |
| `counts.py` | FEAT-001 | `count_objects(model) -> ObjectCounts` |
| `traversal.py` | FEAT-002 (+003) | The only module that knows *where* refs live in the model |
| `resolve.py` | FEAT-002 | `resolve_placeholders`, `assert_fully_resolved` — inverse of normalize |
| `datasource.py` | FEAT-002 | `build_data_source`, `ensure_data_source` — warehouse adapters |
| `preflight.py` | FEAT-002 (+006) | Everything that can fail before a byte is written |
| `backup.py` | FEAT-002 | `backup_workspace(sdk, profile, workspace_id) -> Path \| None` |
| `publish.py` | FEAT-002 (+004) | `publish_workspace`, `publish_domains` |
| `compare.py` | FEAT-002 | Idempotency and cross-org equivalence |
| `domains.py` | FEAT-003 | Manifest schema, strict loader, canonical dumper |
| `coverage.py` | FEAT-003 | `check_coverage(model, manifest) -> CoverageReport`, `raise_for_report` |
| `domain_bootstrap.py` | FEAT-003 | One-time `domains.yaml` generator |
| `maql.py` | FEAT-004 | The only module that knows MAQL reference syntax |
| `refs.py` | FEAT-004 | The only module that knows where refs hide in non-MAQL content |
| `closure.py` | FEAT-004 | `build_closure(model, domain, manifest) -> DomainClosure` |
| `prune.py` | FEAT-004 | `build_entity_index`, join-ancestor fixpoint |
| `split.py` | FEAT-004 | `split_domain`, and the all-domains driver |
| `verify.py` | FEAT-004 / FEAT-006 | **Split ownership — see note below** |
| `ai_context.py` | FEAT-004 | Per-domain filtering of the AI channels |
| `classify.py` | FEAT-006 | Failure taxonomy (ported from predecessor `classifier.py`) |
| `execute.py` | FEAT-006 | `execute_visualization(...)` — AFM execution with timeout + retry |
| `expect.py` | FEAT-006 | Expectations computed from committed artifacts, never from a live org |
| `equivalence.py` | FEAT-006 | `compare_orgs(...) -> EquivalenceReport` |
| `rebuild.py` | FEAT-006 | `RebuildStep` chain — the "no manual step" proof |
| `report.py` | FEAT-006 | The only module that knows about presentation |
| `cli.py` | all | Subcommand registration only; no logic |

FEAT-005 (sole owner): `registry.py`, `archive.py`, `dataload.py`, `sqlcheck.py`,
`search_event.py`, and the `loaders/` submodule (`base.py`, `motherduck.py`, `postgres.py`).
Plus the one-shot `scripts/take_custody.py`, which is not part of the runtime CLI.

> **`verify.py` collision — resolve before building either feature.** FEAT-004 specifies
> `verify_child(child_model, domain_key) -> None` (the two-directional split gate, pure, offline);
> FEAT-006 specifies `verify_target(sdk, profile, domains, ...)` (live read-only verification).
> Two features claim one module name for unrelated concerns. Recommended: FEAT-004 keeps
> `verify.py`, FEAT-006 takes `verification.py`. Whoever builds first updates this row.

## Errors

`GlobalmartError` is the package base exception; every module-specific error subclasses it
(`DomainManifestError`, `UnresolvedLayoutError`, `UnsupportedWarehouseError`, …). Failures are
loud: no silent drop, no partial success reported as success.

## Shared types

### `TargetProfile` — `config.py`, frozen dataclass

One entry in `config/targets.yaml`. Tokens and secrets are **env-only**, never in YAML.

| Field | Type | Added by |
|---|---|---|
| `name` | `str` (YAML key) | FEAT-001 |
| `host` | `str` | FEAT-001 |
| `token` | `str` — env `GLOBALMART_TOKEN__<NAME>`, fallback `GLOBALMART_TOKEN` | FEAT-001 |
| `organization_id` | `str` | FEAT-001 |
| `datasource_id` | `str` | FEAT-001 |
| `datasource_schema` | `str` | FEAT-001 |
| `parent_workspace_id` | `str`, default `"globalmart"` | FEAT-001 |
| `warehouse_type` | `WarehouseType` | FEAT-002 |
| `datasource_name`, `datasource_url`, `datasource_database`, `datasource_username`, `datasource_secret_env` | `str` | FEAT-002 |
| `workspace_id_prefix`, `backup_dir` | `str` | FEAT-002 |
| `warehouse_database` | `str \| None` (MotherDuck `gd_demo`) | FEAT-005 |
| `data_out` | path | FEAT-005 |

`load_profile(name: str) -> TargetProfile` keeps its FEAT-001 signature; only the dataclass grows.
`validate_for_publish(profile) -> list[str]` returns the names of missing publish-required keys,
including an unresolved secret env var.

`WarehouseType` (`StrEnum`): `MOTHERDUCK = "motherduck"`, `POSTGRES = "postgres"`. Any other value
raises at **profile-load** time, not at publish time.

`organization_id`, `datasource_id` and `datasource_schema` are read in both directions — what to
scrub out on capture, what to substitute back in on publish. That symmetry is what makes the
portability contract testable; do not split them into separate fields.

### Placeholder tokens — `normalize.py` module constants

```python
DATASOURCE_ID_TOKEN     = "{{ datasource_id }}"
DATASOURCE_SCHEMA_TOKEN = "{{ datasource_schema }}"
```

Import these; never re-declare the literals. `{{ datasource_schema }}` is **substituted** at
publish time, never stripped and never left templated — that is a known predecessor defect class.
All rewriting is structured field assignment on the SDK attrs model, never string replacement on
YAML text.

### Domain manifest types — `domains.py` (owned by FEAT-003)

```python
@dataclass(frozen=True)
class AiSelection:
    memory_item_ids: tuple[str, ...]
    memory_item_tags: tuple[str, ...]     # RULE, not ids: an item carrying any listed tag is in
    parameter_ids: tuple[str, ...]
    agent_ids: tuple[str, ...]
    knowledge_ids: tuple[str, ...]

@dataclass(frozen=True)
class Domain:
    key: str                              # snake_case, e.g. "store_ops"
    label: str                            # human label — NOT the published workspace name
    description: str
    workspace_id: str                     # "globalmart-store-ops" (key underscores -> hyphens)
    workspace_name: str | None            # per-domain override of the name template
    dashboards: tuple[str, ...]           # explicit analyticalDashboard ids
    visualizations: tuple[str, ...]       # extra visualizationObject ids not reachable from them
    ai: AiSelection                       # NESTED — there are no flat ai id fields on Domain
    ldm_include: tuple[str, ...]          # dataset ids seeded into the LDM beyond closure, for
                                          # authoring headroom. NOT coverage, NOT `shared:` —
                                          # an LDM concern only. Default empty.

@dataclass(frozen=True)
class Exclusion:
    id: str
    reason: str

@dataclass(frozen=True)
class SharedSelection:                    # belongs in EVERY child
    dashboards: tuple[str, ...]
    visualizations: tuple[str, ...]
    ai: AiSelection

@dataclass(frozen=True)
class UnassignedSelection:                # deliberate, reasoned exclusions
    dashboards: tuple[Exclusion, ...]
    visualizations: tuple[Exclusion, ...]
    ai: tuple[Exclusion, ...]

@dataclass(frozen=True)
class DomainManifest:
    version: int
    parent_workspace_id: str              # "globalmart"
    workspace_id_template: str            # default "globalmart-{key_kebab}"
    workspace_name_template: str          # default "GlobalMart — {label}"
    domains: tuple[Domain, ...]           # ordered by key, 12 today
    shared: SharedSelection
    unassigned: UnassignedSelection
    path: Path

    def by_key(self, key: str) -> Domain: ...
    def keys(self) -> tuple[str, ...]: ...
    def resolve_workspace_name(self, domain: Domain) -> str: ...  # override else template
    def unassigned_ids(self) -> frozenset[str]: ...               # flattened exclusion ids

def load_domains(path: Path) -> DomainManifest: ...
def dump_domains(manifest: DomainManifest, path: Path) -> Path: ...
def key_kebab(key: str) -> str: ...        # store_ops -> store-ops
class DomainManifestError(GlobalmartError): ...
```

Consumers use the accessor methods; do not re-derive name resolution or flatten exclusions
by hand. `domain.label` is never passed as a workspace name — call `resolve_workspace_name`.

`resolve_workspace_id` and `resolve_workspace_name` are **methods on `DomainManifest` only**
(built 2026-09-18) — there are no module-level twins. Two spellings of one operation is how a
caller ends up using the one that skips the per-domain override.

## CLI surface

Single entry point `globalmart`, subcommands registered in `cli.py`:

| Command | Feature |
|---|---|
| `globalmart bootstrap` | FEAT-001 |
| `globalmart normalize [--check]` | FEAT-001 (`--check` is a CI gate) |
| `globalmart publish parent --target <profile> [--workspace-id <id>] [--apply]` | FEAT-002 |
| `globalmart domains validate \| bootstrap [--manifest config/domains.yaml]` | FEAT-003 |
| `globalmart split [--domains-file ...] [--from <layout>] [--check]` | FEAT-004 |
| `globalmart publish domains --target <profile> [--apply]` | FEAT-004 |
| `globalmart data fetch [--manifest data/archive-manifest.json] [--force] [--dry-run]` | FEAT-005 |
| `globalmart data load --target <profile> [--apply] [--only <table>]` | FEAT-005 |
| `globalmart verify --target <profile> [--workspace <id> ...] [--max-workers N]` | FEAT-006 |
| `globalmart rebuild` | FEAT-006 |

**Flag convention (from STEERING.md, binding):** `--apply` gates writes to a live org — every such
command is a read-only rehearsal by default. `--dry-run` belongs only to commands whose writes are
local files. **No command has both.** `--check` means "verify the committed artifact is current,
exit non-zero otherwise" and is the CI gate form.

## On-disk paths

| Path | What | Committed? |
|---|---|---|
| `layouts/workspaces/globalmart/` | Parent workspace, SDK native YAML tree, one file per object. Neutral path — **no org id** | yes |
| `generated/workspaces/globalmart-<domain>.json` | The 12 derived children, declarative JSON | yes (ADR 003) |
| `.cache/globalmart-data/` | Fetched + extracted CSVs | **no** — gitignored, re-fetched from the pinned archive |
| `config/targets.yaml` | Publish target profiles. Zero secrets | yes |
| `config/domains.yaml` | Domain membership manifest | yes |
| `data/ddl/globalmart.sql` | 214-table DDL, schema-only, `{schema_name}` templated | yes |
| `data/archive-manifest.json` | Archive version, URL, sha256, per-table row counts and checksums | yes |
| `backups/`, `reports/` | Runtime output | no |

Layout I/O goes through `get_declarative_workspace(...).store_to_disk(workspace_folder=...)` and
`CatalogDeclarativeWorkspaceModel.load_from_disk(workspace_folder=...)` — **never**
`store_declarative_workspace` / `load_declarative_workspace`, which route through
`layout_organization_folder()` and bake the org id into the path.

Children are **derived, never authored**. Hand-editing a file under `generated/` is a defect: fix
the parent or `domains.yaml` and regenerate.

## Test fixtures

| Fixture | Owner | Reused by |
|---|---|---|
| `tests/fixtures/mini_globalmart/` | FEAT-001 | FEAT-002 (unchanged), FEAT-003 (extended: second dashboard spanning two domains) |
| `tests/fixtures/published_layouts/` | FEAT-002 | — |
| `tests/fixtures/domains/` | FEAT-003 | — |
| `tests/fixtures/mini_domains/` | FEAT-004 | FEAT-006 (2-domain miniature of FEAT-004 output) |
| `tests/fixtures/expected_children/` | FEAT-004 | — |
| `tests/fixtures/data_manifest_scale_0_01.json` | FEAT-005 | determinism oracle |
| `tests/fixtures/verification/` | FEAT-006 | — |

Extend an existing fixture rather than adding a parallel one.

---

*Change this file in the same commit as the code that changes an interface. A breakdown that
contradicts it is the breakdown's bug.*
