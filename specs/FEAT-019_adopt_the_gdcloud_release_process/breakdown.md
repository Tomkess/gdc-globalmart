---

## Technical Breakdown — FEAT-019: Adopt the gdcloud release process (one data product: globalmart)

Inputs: `spec.md` (re-scoped 2026-10-22), `spike.md`, `specs/STEERING.md`, `specs/CONTRACT.md`, `breakdown.superseded.md` (the 13-DP design, reused where it still applies), `Services-MIC-Cloud/config.yml`, `config/targets.yaml`.

What changed against the superseded design, and why the shape is now simpler:

- **One data product.** `globalmart` (label `GM`) is the only gdcloud DP. The 12 domain workspaces are local-only artifacts: `split --check` and `domains validate --strict` keep gating `generated/`, and `globalmart publish domains --target <t> --apply` redeploys them on demand. No gdcloud workflow ever creates one. This removes the 13-label catalog, the `derived_current` per-domain projection, the `id_prefix` audit across domains, and the per-domain equivalence proofs.
- **Settled decisions (not reopened here).** D1 snake ids `globalmart_{dev,test,preprod,master}`. D2 Stage A: `layouts/workspaces/globalmart/` stays the authoring surface, `gd_data_product/globalmart/` is a `--check`-gated projection. D6 new data source `gdc_ds_globalmart_motherduck` on both orgs. gdcloud `v0.51.0`, Python 3.14, `allow-direct-references`. Labels `GM` + `TOOLING`. D8 `production-post` Environment for the prod knowledge step. **preprod/prod are in scope** (no FEAT-019b).
- **Spike facts used as inputs, not re-investigated.** `gooddata-sdk==1.75.0` resolves with gdcloud (D3). 789 tests pass on 3.14 (D4). `sql_dialect: duckdb`, and labels have no character-class rule (D7). gdcloud pushes the SDK's full `CatalogDeclarativeAnalytics`, memory items replace by default, and a missing `workspace_data_filters.json` is a no-op upload (D5, offline). The live round trip is still owed. demo.cloud now holds 13/25 workspaces, so the 2 new workspaces there (`globalmart_dev`, `globalmart_test`) fit.
- **The routine path stays offline.** STEERING forbids routine capture-from-live, so `gd-store` is used only in the one-time round-trip proof (C11). Every change flows `layouts/` → `globalmart gdcloud project` → `gd_data_product/globalmart/` → PR → gdcloud workflows.
- **Data plane is environment-independent.** All four environments read MotherDuck `gd_demo`, schema `globalmart`. "Data before workspace" is one warehouse precondition gated before merge, not a per-environment step.

---

### Components

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|
| **C1. Toolchain & gdcloud pin** | `pyproject.toml`: add `"gdcloud @ git+https://github.com/gooddata/gd-cloud-tooling.git@v0.51.0"`, `requires-python = ">=3.14"`, `[tool.mypy] python_version = "3.14"`, `[tool.uv] package = true`, `[tool.hatch.metadata] allow-direct-references = true` (spike: without it `uv sync` fails), entry point `[project.entry-points."gdcloud.ci_checks"] globalmart = "gd_plugin.checks:CHECKS"`, and `gd_plugin` added to `[tool.hatch.build.targets.wheel] packages`. Keep `gooddata-sdk==1.75.0`. New files: `.python-version` (`3.14`), `Makefile` (MIC targets `dev`, `adopt`, `store`, `upload`, `validate`, `ci`, `format`, `lint`, `help`, plus project targets `project` → C4 and `project-check`), `.yamllint`, and `.gitignore` entry `gd_output/`. CI interpreter moves to 3.14 | Existing (modify) + new files | S |
| **C2. Root `config.yml`** | One DP, four environments on two hosts, `primary_data_product: globalmart`, `default_git_branch: main`, `sql_dialect: duckdb`, `automation.org_release` / `organization_snapshot` hard-off (Data Model §2). Bootstrapped with `gd-init --pull` into a scratch dir and merged by hand; the committed file is the hand-merged one | New | S |
| **C3. `gdcloud_bridge.py`** | The only module in `src/globalmart/` that reads `config.yml`. `load_release_config(path) -> ReleaseConfig`, `master_workspace_id(cfg, env) -> str`, `release_scope_from_tags(env, since, *, repo) -> ReleaseScope \| None` (parses `deploy-{env}-globalmart-{ver}-{ts}`). Reads YAML directly, so the `globalmart` package has no runtime import of `gdcloud` (gdcloud stays a CI/tooling dependency). Raises `ReleaseConfigError(GlobalmartError)` on a catalog of ≠ 1 DP, an env missing the DP, or a master id that does not match `globalmart_<suffix>` | New | S |
| **C4. Projector — `globalmart gdcloud project`** | Offline, deterministic. Loads the parent with `layout_io.read_tree(layouts/workspaces/globalmart/)`, resolves `{{ datasource_id }}` → `gdc_ds_globalmart_motherduck` and `{{ datasource_schema }}` → `globalmart` via `resolve.resolve_placeholders` with a synthetic canonical `TargetProfile`, then `assert_fully_resolved`. Asserts no `createdBy`/`modifiedBy` and no WDFs. Writes `gd_data_product/globalmart/{ldm,analytics_model}/` with gdcloud's per-object YAML writer (its public writer if exported, otherwise `store_to_disk` into a temp dir + `gd-format-yaml`). Deletes stale files inside those two folders only. Flags: `--layout`, `--out` (default `gd_data_product`), `--dry-run`, `--check`. Never reads a live org. Canonicalization surfaced by C11 is folded in here | New (`gdcloud_project.py`) | M |
| **C5. `TargetProfile.gdcloud_environment` + four profiles** | `config.py` gains `gdcloud_environment: str \| None = None` (YAML only). At profile-load: the value must name an env in `config.yml`; `parent_workspace_id` must equal that env's `master_workspace_id` (C3); `knowledge_scope: organization` is rejected (both orgs are shared, ADR 010). `knowledge_docs.corpus_workspaces` gets one branch: when `gdcloud_environment` is set it returns `(parent_workspace_id,)` only, regardless of `--domains-file`, so a forgotten `--parent-only` can never target a domain workspace. `config/targets.yaml` gains `gdcloud-dev`, `gdcloud-test`, `gdcloud-preprod`, `gdcloud-prod` (Data Model §5). CONTRACT amended in the same commit | Existing (modify `config.py`, `knowledge_docs.py`, `targets.yaml`) | S |
| **C6. Environment bootstrap — `globalmart gdcloud bootstrap`** | Live, rehearsal by default, writes only with `--apply` (ADR 002). For one `--environment`: (a) **capacity check**: `GET /api/v1/entities/entitlements` (`WorkspaceCount`) vs `GET /api/v1/actions/collectUsage`; fails if the master does not exist and no slot is free (raw REST, SDK gap noted in a comment). (b) **collision audit**: fails if the planned master id exists with a title that does not start with `GlobalMart`. (c) `datasource.ensure_data_source` for `gdc_ds_globalmart_motherduck` (MotherDuck `gd_demo`, secret from `MOTHERDUCK_TOKEN`). (d) pre-creates the master with its env title through `catalog_workspace.create_or_update`, because gdcloud titles a self-created master with the bare DP id. `backup.backup_workspace` runs before any overwrite of an existing master. Flags `--environment` (req), `--apply`, `--no-backup` | New (`gdcloud_bootstrap.py`) | M |
| **C7. `gd_plugin/` checks** | Registered via `gdcloud.ci_checks`, run by `gd-ci` in `check_ci_checks.yml`. `projection_current`: runs C4 in memory and fails if `gd_data_product/globalmart/` differs, so a hand edit or a workflow 2a store is a red build. `org_scope`: fails if `automation.org_release.enabled` or `automation.organization_snapshot.enabled` is truthy, or if `gd_organization/` / `gd_organization_snapshot/` exists (ecommerce ADR 002). `CHECKS` exported from `gd_plugin/checks/__init__.py`, `source="gd_plugin"` | New | S |
| **C8. Workflow adoption** | `uv run gd-workflows adopt .` (via `make adopt`). Expected payload: `1__…`, `1b__…`, `2a__…`, `2b__…`, `3__automated_deployment_dev_main`, `4_manual_deployment_test`, `5_manual_deployment_prod` (preprod then prod), `6_version_comparison`, `check_*`, `auto_gdcloud_pin`, `branch_gate`, `pr_path_gate`, vendored actions/scripts and `.github/gdcloud-ci.version`. No `4a_*`, `5a_*`, `org_release.yml`, `auto_org_snapshot.yml`. Nothing hand-edited; `check_ci_payload.yml` green. Under Stage A, 1/1b/2a/2b are adopted but not part of the routine path (README says so); `projection_current` catches a 2a store | New (generated) | M |
| **C9. Project-owned workflows** | Beside the generated payload, never inside it. (a) `ci.yml` (existing): add `globalmart gdcloud project --check` after `split --check`, and a job `data-current` running `globalmart data ensure --target gdcloud-dev --check`. Both become required checks on `main`, so they gate workflow 3. `split --check` and `domains validate --strict` stay. (b) **New `globalmart_post_deploy.yml`**: `on: workflow_run` of the generated 3/4/5 `name:`s, `types: [completed]`, job `if: conclusion == 'success'`. Step 1 runs `globalmart gdcloud scope --since <run_started_at> --format json` to get `{environment, version}` from the deploy tag the run wrote, and exits 0 when there is none (TOOLING-only merge). Step 2 selects the GitHub Environment (`develop`/`staging`/`preprod`/`production-post`), maps `TOKEN_GOODDATA` → `GLOBALMART_TOKEN__GDCLOUD_<ENV>`, and runs `globalmart knowledge-docs publish --target gdcloud-<env> --parent-only --workspace-id globalmart_<suffix> --apply`, then `knowledge-docs verify` with the same flags. (c) `data-currency.yml` (existing): retargeted from `demo-cloud-rebuild` to `gdcloud-dev --apply`, with GoodData cache invalidation reaching `gdc_ds_globalmart_motherduck` on **both** orgs (matrix over `gdcloud-dev` and `gdcloud-prod`) | Existing (modify) + new | M |
| **C10. CLI surface additions** | Registered in `cli.py` (registration only): `globalmart gdcloud project` (C4, local), `globalmart gdcloud bootstrap` (C6, live `--apply`), `globalmart gdcloud scope` (`--environment`, `--since` (req), `--format {text,json}`; read-only, reads git tags only). `globalmart data ensure` gains `--check`: read-only, exit 3 when the rehearsal plan contains any write; mutually exclusive with `--apply`. CONTRACT CLI table and `tests/test_cli.py` amended in the same commit | Existing (modify) + new | S |
| **C11. Live round-trip proof** | One-time, user-approved (STEERING § AI Behavior). On a scratch master `globalmart_spike` (slot now free on demo.cloud): `gd-upload` the projected DP, `gd-store` into a scratch copy, `diff -r` against the committed projection. Must be empty, including `memory_items/`, `parameters/`, `attribute_hierarchy_objects/`, `analytical_dashboard_extensions/` and `export_definitions`. Any gdcloud canonicalization (e.g. `normalize_analytics_empty_tags`, YAML formatting) is folded into C4 until the diff is empty. Then `gd-validate` and `gd-ci run --all` green; scratch workspace deleted afterwards | New (process) | M |
| **C12. GitHub setup** | Environments `develop`, `staging`, `preprod`, `production` (required reviewers, branch policy `main` + `hotfix/*`), `production-post` (same token as `production`, no reviewers, `main` only, D8). Each holds `TOKEN_GOODDATA` and `MOTHERDUCK_TOKEN`. Repo secrets `TOKEN_GITHUB_GDCLOUD` (pin fetch) and `TOKEN_GITHUB_ADMIN` (tag pushes; `GITHUB_TOKEN` tags do not trigger workflows). Labels `GM`, `TOOLING`. Branch protection on `main`: PR label, CI checks, AFM, YAML formatting, yamllint, `CI / check`, `CI / data-current` | Existing (GitHub settings) | S |
| **C13. Domains & legacy disposition** | No code. Domain workspaces: `domains.yaml`, `generated/workspaces/*.json`, the splitter and `publish domains` stay; no gdcloud path touches them. Legacy: `globalmart` workspace and `demo-cloud`/`demo-cloud-rebuild`/`usecases-ai` profiles stay as ad hoc targets, as do `config/agents.yaml` and `mcp-tools.json` (orchestrator repoint is a follow-on). `normalize.py` stays (it produces the placeholder form C4 resolves); retiring it is Stage B | Existing (document only) | S |
| **C14. Docs, STEERING, CONTRACT, ADR 011** | README release section: env ↔ org ↔ workspace table, label rules (`GM` deploys, `TOOLING` does not), promotion and hotfix how-to, "org-level objects are owned by the org repo", and the on-demand domain redeploy command plus the note that the A2A/MCP demo needs it. STEERING: Python 3.11+ → 3.14; rules "never enable `org_release` / `organization_snapshot`", "`gd_data_product/globalmart/` is derived — regenerate with `gdcloud project`", "domain workspaces are local-only, never released". CONTRACT: module rows `gdcloud_bridge.py`, `gdcloud_project.py`, `gdcloud_bootstrap.py`; `TargetProfile.gdcloud_environment`; CLI rows; path rows `config.yml`, `gd_data_product/globalmart/`, `gd_plugin/`. New `specs/decisions/011-gdcloud-release-of-globalmart.md`. Merge the gdcloud-seeded `AGENTS.md` | Existing (modify) + new | M |
| **C15. End-to-end validation** | Scripted walkthrough across all four environments (Test Strategy, integration steps): label-scoped workflow 3, workflow 4 to test, workflow 5 to preprod then prod, isolation between same-org siblings, post-deploy ordering, hotfix | New (process) | M |

---

### Data Model

#### 1. ID scheme (two shared orgs, workspace-separated, ecommerce ADR 001)

| Object | dev | test | preprod | prod |
|---|---|---|---|---|
| Host / org | `petertomko.demo.cloud` / `gm-ddebmti` | ← same org | `usecases-ai.demo.cloud` / `w2r-kigdm6` | ← same org |
| DP id / label | `globalmart` / `GM` | ← | ← | ← |
| Master workspace | `globalmart_dev` | `globalmart_test` | `globalmart_preprod` | `globalmart_master` |
| Master title (C6) | `GlobalMart (DEV)` | `GlobalMart (TEST)` | `GlobalMart (PREPROD)` | `GlobalMart` |
| Data source | `gdc_ds_globalmart_motherduck` → `gd_demo`.`globalmart` | ← shared | `gdc_ds_globalmart_motherduck` (created by C6) | ← shared |
| GitHub Environment | `develop` | `staging` | `preprod` | `production` (+ `production-post`) |
| Tags | `v1.N`, hotfix `v1.N.M`, `deploy-{env}-globalmart-{ver}-{ts}` | ← | ← | ← |

The legacy `globalmart` workspace and the 12 `globalmart-<domain>` ids cannot collide: none of the new ids is a bare `globalmart`, and `_` differs from `-`. Workspace budget: +2 on demo.cloud (13 → 15 of 25); +2 on AI Usecases (cap unknown — C6 checks it before creating).

#### 2. Root `config.yml`

```yaml
default_git_branch: "main"
sql_dialect: duckdb                       # gdcloud maps MOTHERDUCK -> duckdb (spike D7)
github_token_variable: "TOKEN_GITHUB_ADMIN"
github_dependency_token_variable: "TOKEN_GITHUB_GDCLOUD"

# ecommerce ADR 002: org-level objects are released ONLY by the org repo.
# gd_plugin/checks/org_scope.py fails gd-ci if either becomes true.
automation:
  org_release:            {enabled: false}
  organization_snapshot:  {enabled: false}
  version_comparison:     {enabled: true}
  scheduled_model_validation: {enabled: false}
  translation_source:     {enabled: false}
  tag_documentation:      {enabled: false}
  metadata_export:        {enabled: false}

workflows:
  check_ci_checks:
    additional_paths: '^gd_plugin/|^config\.yml$|^pyproject\.toml$|^layouts/workspaces/globalmart/|^gd_data_product/([^/]+/)?config\.env\.yml$'

primary_data_product: "globalmart"

data_products:
  globalmart:
    label: GM

environments:
  dev:
    host: "https://petertomko.demo.cloud.gooddata.com"
    gooddata_token_variable: "GLOBALMART_TOKEN__GDCLOUD_DEV"
    github_environment: "develop"
    data_products:
      globalmart:
        master_workspace_id: "globalmart_dev"
        delete_invalid_metrics: false        # split/verify gates own consistency; a deploy
        delete_invalid_visualizations: false # must never silently diverge the org from git
        create_clone: false
  test:
    host: "https://petertomko.demo.cloud.gooddata.com"     # same org as dev
    gooddata_token_variable: "GLOBALMART_TOKEN__GDCLOUD_TEST"
    github_environment: "staging"
    data_products:
      globalmart: {master_workspace_id: "globalmart_test", create_clone: false}
  preprod:
    host: "https://usecases-ai.demo.cloud.gooddata.com"
    gooddata_token_variable: "GLOBALMART_TOKEN__GDCLOUD_PREPROD"
    github_environment: "preprod"
    data_products:
      globalmart: {master_workspace_id: "globalmart_preprod", create_clone: false}
  prod:
    host: "https://usecases-ai.demo.cloud.gooddata.com"     # same org as preprod
    gooddata_token_variable: "GLOBALMART_TOKEN__GDCLOUD_PROD"
    github_environment: "production"
    protected: true
    data_products:
      globalmart: {master_workspace_id: "globalmart_master", create_clone: false}
```

`create_clone: false` everywhere: GlobalMart has no tenant clones, and a clone would spend a workspace slot. Token variable names follow the `GLOBALMART_TOKEN__<PROFILE>` convention, so one env var serves both `gd-*` and `globalmart --target gdcloud-<env>`.

#### 3. On-disk layout

```
config.yml
gd_data_product/
  config.env.yml                  # common env layer, header only (no datasource_mappings needed)
  globalmart/                     # DERIVED from layouts/workspaces/globalmart/ by C4
    ldm/datasets/*.yaml           # all 225 dataSourceId refs resolved to gdc_ds_globalmart_motherduck
    ldm/date_instances/*.yaml
    analytics_model/{analytical_dashboards,analytical_dashboard_extensions,
                     attribute_hierarchy_objects,dashboard_plugins,filter_contexts,
                     memory_items,metrics,parameters,visualization_objects}/*.yaml
    # no workspace_data_filters.json: WDF drop policy; gdcloud upload is a no-op (spike D5)
gd_plugin/
  __init__.py
  checks/__init__.py              # CHECKS = [projection_current.SPEC, org_scope.SPEC]
  checks/projection_current.py
  checks/org_scope.py
```

The exact `analytics_model/` subfolder set is whatever gdcloud's writer emits; C11 confirms it covers every class the parent has.

#### 4. Projection contract and types

| Concern | Rule |
|---|---|
| Input | `layout_io.read_tree(Path("layouts/workspaces/globalmart"))` only. `generated/` is never read |
| `DATASOURCE_ID_TOKEN` | → `gdc_ds_globalmart_motherduck`, structured traversal (`traversal.py`), never string replacement |
| `DATASOURCE_SCHEMA_TOKEN` | → `globalmart`, in SQL statements and `dataSourceTableId.path[0]` (`iter_table_schema_slots`) |
| Canonical profile | Synthetic `TargetProfile(name="gdcloud-canonical", datasource_id=…, datasource_schema=…)` built in code from C3. No host/org enters the tree (Portability Contract) |
| Identity / WDFs | `createdBy`/`modifiedBy` absent (asserted); no WDF emitted |
| AI channels | All `memoryItems` and `parameters` carried unfiltered (single parent DP) |
| Determinism | Sorted file emission; lists not re-sorted (`dataSourceTableId.path` is positional); output passes `gd-format-yaml --check` |
| Staleness | Unproduced files under `globalmart/{ldm,analytics_model}` are deleted (reported under `--check`). `config.*.yml` never touched |

```python
# gdcloud_project.py
@dataclass(frozen=True)
class Projection:
    dp_id: str                         # "globalmart"
    files: dict[Path, bytes]           # path relative to gd_data_product/globalmart/ -> content

def project_parent(layout: Path, cfg: ReleaseConfig) -> Projection: ...
def write_projection(p: Projection, out: Path, *, dry_run: bool) -> list[Path]: ...
def diff_projection(p: Projection, out: Path) -> list[str]: ...   # --check and projection_current
class ProjectionError(GlobalmartError): ...

# gdcloud_bridge.py
@dataclass(frozen=True)
class ReleaseConfig:
    path: Path
    dp_id: str                         # primary_data_product; exactly one catalog entry
    label: str                         # "GM"
    datasource_id: str                 # "gdc_ds_globalmart_motherduck" (canonical value the projector resolves to; see below)
    datasource_schema: str             # "globalmart"
    masters: dict[str, str]            # env -> master_workspace_id
    hosts: dict[str, str]              # env -> host
    github_environments: dict[str, str]  # env -> GitHub Environment name

@dataclass(frozen=True)
class ReleaseScope:
    environment: str                   # "dev" | "test" | "preprod" | "prod"
    version: str                       # "v1.N" | "v1.N.M"
    workspace_id: str                  # masters[environment]

def load_release_config(path: Path = Path("config.yml")) -> ReleaseConfig: ...
def master_workspace_id(cfg: ReleaseConfig, env: str) -> str: ...
def release_scope_from_tags(env: str | None, since: datetime, *, repo: Path = Path(".")) -> ReleaseScope | None: ...
class ReleaseConfigError(GlobalmartError): ...
```

`datasource_id` / `datasource_schema` are the two canonical values the projector resolves to. They are not gdcloud keys, so C3 reads them from `gd_data_product/config.env.yml`'s block `globalmart_canonical: {datasource_id, datasource_schema}` if gdcloud tolerates unknown keys there, otherwise from module constants with a default-matches-convention note (STEERING allows a code default that resolves through config). C1/C2 settles which by running `gd-validate` against the extra key.

#### 5. `TargetProfile` growth and `config/targets.yaml` entries

| Field | Type | Added by |
|---|---|---|
| `gdcloud_environment` | `str \| None`, default `None`. YAML only, no env override. Must name an env in `config.yml`; `parent_workspace_id` must equal that env's master; incompatible with `knowledge_scope: organization`. All three raise at profile-load | FEAT-019 |

```yaml
  gdcloud-dev:                       # gdcloud-test identical except parent_workspace_id/gdcloud_environment
    host: https://petertomko.demo.cloud.gooddata.com
    organization_id: gm-ddebmti
    datasource_id: gdc_ds_globalmart_motherduck
    datasource_schema: globalmart
    parent_workspace_id: globalmart_dev
    warehouse_type: motherduck
    datasource_name: GlobalMart MotherDuck (gdcloud)
    datasource_url: jdbc:duckdb:md:gd_demo
    datasource_database: gd_demo
    warehouse_database: gd_demo
    datasource_secret_env: MOTHERDUCK_TOKEN
    data_owned: true                 # same schema demo-cloud already owns (ADR 004/008)
    knowledge_scope: workspaces      # shared org — never organization level (ADR 010)
    gdcloud_environment: dev

  gdcloud-preprod:                   # gdcloud-prod identical with globalmart_master / prod
    host: https://usecases-ai.demo.cloud.gooddata.com
    organization_id: w2r-kigdm6
    datasource_id: gdc_ds_globalmart_motherduck
    datasource_schema: globalmart
    parent_workspace_id: globalmart_preprod
    # … same warehouse keys as gdcloud-dev …
    data_owned: true
    knowledge_scope: workspaces
    gdcloud_environment: preprod
```

---

### Integration Points

**Content flow (authoring → release):**

```
edit layouts/workspaces/globalmart/
  → globalmart split            (local; keeps generated/ current — domains stay local artifacts)
  → globalmart gdcloud project  (local; writes gd_data_product/globalmart/)
  → PR labelled GM (or TOOLING for non-content)
  → gates: ci.yml (normalize/split/domains/project --check, data-current)
           + gdcloud check_* (label, AFM, yamllint, gd-ci incl. projection_current, org_scope)
  → merge → workflow 3: tag v1.N, gd-upload → globalmart_dev, tag deploy-dev-globalmart-v1.N-<ts>
  → globalmart_post_deploy.yml: knowledge-docs publish + verify → globalmart_dev
  → workflow 4 → globalmart_test → post_deploy
  → workflow 5 → globalmart_preprod → post_deploy; then prod after `production` approval
               → globalmart_master → post_deploy in `production-post`
```

| System | Touch point | Notes / constraints |
|---|---|---|
| **gdcloud v0.51.0** | Pinned git dependency; `gd-init --pull` (scratch), `gd-upload`/`gd-store` (C11 + workflows), `gd-validate`, `gd-ci`, `gd-format-yaml`, `gd-version`, `gd-hotfix`, `gd-workflows adopt/sync`; entry point `gdcloud.ci_checks` | No fork, no hand-edited workflow. Upstream asks worth filing: env-labelled master titles (retires C6(d)), a post-deploy hook group (retires C9(b)) |
| **`resolve.py` / `traversal.py` / `layout_io.py` (FEAT-001/002)** | C4 calls `read_tree`, `resolve_placeholders`, `assert_fully_resolved` | No new traversal. A slot `resolve` misses is a FEAT-002 defect fixed there |
| **`datasource.py` / `backup.py` (FEAT-002)** | C6 calls `ensure_data_source`, `backup_workspace` | Unchanged signatures |
| **Splitter (FEAT-003/004)** | None at release time | `split --check`, `domains validate --strict` stay in `ci.yml`. `publish domains` remains the only way a domain reaches an org |
| **Data (FEAT-005/013, ADR 008)** | `data ensure --check` required PR check; `data-currency.yml` scheduled `--apply` | One schema behind four envs, so the warehouse is current before any merge can trigger workflow 3. Cache invalidation (commit `c845ddd`) must reach both orgs' `gdc_ds_globalmart_motherduck` |
| **Knowledge corpus (FEAT-015/017/018, ADR 009/010)** | Post-deploy `knowledge-docs publish/verify --target gdcloud-<env> --parent-only --workspace-id globalmart_<suffix>` | Order data → workspace → knowledge holds structurally: data gated pre-merge, workspace deployed by 3/4/5, knowledge only on `workflow_run` success. `tests/test_release_wiring.py` pins the trigger names to the generated `name:` values |
| **AI memory / parameters (in-layout)** | Travel in `gd_data_product/globalmart/analytics_model/` | gdcloud replaces workspace items with committed ones by default — the repo is the truth. C11 proves it live |
| **Org repo (ecommerce ADR 002)** | None | `org_scope` guards the two automation flags and the `gd_organization*/` folders |
| **ecommerce repo / shared orgs** | Same hosts, same Environment names, same pin line | Coordinate pin and Environment names only. ids differ by construction (`globalmart_*` vs `ecommerce_*`); C6 audit runs before each first deploy |
| **A2A/MCP orchestrator (FEAT-009/010/014)** | None | Still points at legacy `globalmart-<domain>` (deleted from demo.cloud 2026-10-22). Down until `publish domains` is rerun — documented, accepted |
| **GitHub** | Environments, secrets, labels, branch protection, PAT tag pushes | `workflow_run` runs the default-branch copy of `globalmart_post_deploy.yml`, so a PR cannot alter it before it runs with deploy credentials |
| **CONTRACT.md** | Amended with C3/C4/C5/C6/C10 | New modules, `TargetProfile.gdcloud_environment`, CLI rows incl. `data ensure --check`, path rows |

---

### Test Strategy

**Unit (pytest, offline; extend `tests/fixtures/mini_globalmart/`, no parallel fixture)**
- `gdcloud_project`: projects one DP; no `{{ … }}` survives; every `dataSourceId` is `gdc_ds_globalmart_motherduck`; `dataSourceTableId.path` order preserved; second run byte-identical; `--check` passes on fresh output and fails on a hand-edited metric, a stale extra file, and a missing dataset; `--dry-run` writes nothing; `config.env.yml` untouched; `memory_items/` and `parameters/` present when the fixture has them.
- `gdcloud_bridge`: loads the committed `config.yml`; exactly one DP with label `GM`; masters are `globalmart_{dev,test,preprod,master}`; dev/test share a host, preprod/prod share a host; `prod.protected` is true; `release_scope_from_tags` parses `deploy-prod-globalmart-v1.7.1-20261022T101500`, returns `None` when no tag is newer than `since`; unknown env raises.
- `config.py`: `gdcloud_environment` naming a missing env raises; `parent_workspace_id` ≠ master raises; `knowledge_scope: organization` + `gdcloud_environment` raises. All four `gdcloud-*` profiles load.
- `knowledge_docs.corpus_workspaces`: `gdcloud-test` → `("globalmart_test",)` even with `--domains-file`; `demo-cloud` unchanged.
- `gd_plugin`: `org_scope` fail/fail/fail/pass (org_release on, snapshot on, `gd_organization/` exists, clean); `projection_current` fails on a hand edit under `gd_data_product/globalmart/`.
- `gdcloud_bootstrap` (mocked SDK + REST): rehearsal writes nothing; titles per env; capacity check fails at cap and passes when the master already exists; audit aborts on a foreign-titled `globalmart_test`; backup precedes overwrite.
- `data ensure --check`: exit 0 when current, 3 when a write is planned, usage error with `--apply`.
- `tests/test_release_wiring.py`: generated 3/4/5 `name:` values ⊆ `globalmart_post_deploy.yml` `workflow_run.workflows`; no `4a_*`, `5a_*`, `org_release.yml`, `auto_org_snapshot.yml`; `ci.yml` runs `split --check`, `domains validate --strict` and `gdcloud project --check`; env → GitHub Environment mapping in the post-deploy job equals `config.yml` (prod → `production-post`).
- `tests/test_cli.py`: new rows parse; no command has both `--apply` and `--dry-run`.

**Static / CI gates**
- `gd-validate`, `gd-ci run --all` green; `gd-ci list` shows `projection_current` and `org_scope`.
- `gd-workflows adopt . --check` no drift; `check_ci_payload.yml` green; `gd-format-yaml --check`, `yamllint`, existing `ci.yml` green; `ruff`, `mypy` (3.14) clean.

**Integration — live, each run user-approved**
1. C11 on `globalmart_spike`: `gd-upload` → `gd-store` → `diff -r` empty; scratch deleted.
2. `gdcloud bootstrap --environment dev` rehearsal then `--apply`; same for `test`. Titles `(DEV)`/`(TEST)`, data source present, demo.cloud at 15/25.
3. `globalmart verify --target gdcloud-dev --workspace globalmart_dev`: every visualization executes, none empty.
4. PR editing one parent metric, labelled `GM`: merge → `v1.N`, `deploy-dev-globalmart-v1.N-…`; post-deploy publishes and verifies the corpus in `globalmart_dev` only.
5. `TOOLING`-only PR: no deploy, post-deploy exits 0 with no scope.
6. Hand edit under `gd_data_product/globalmart/`: `CI / check` and `projection_current` red.
7. Isolation: capture `globalmart_dev` layout + `modifiedAt`; run workflow 4 → `globalmart_test` updated, dev byte-identical. Repeat for preprod vs prod.
8. Ordering: `data-current` red (simulated stale schema via a scratch profile) blocks merge.
9. AI Usecases: `bootstrap --environment preprod|prod --apply` after the capacity check; workflow 5 preprod (no approval), then prod (waits on `production`); post-deploy runs in `production-post`.
10. `globalmart verify equivalence --target-a gdcloud-test --target-b gdcloud-preprod --workspace-id …`: equal except parameterized values (Portability Contract across the release path).
11. Hotfix: `gd-hotfix` cuts `hotfix/*` from the last prod tag, ships `v1.N.1` to prod through `production`.

**Manual**
- README walkthrough by a newcomer: explain env ↔ org ↔ workspace, run a promotion, redeploy the domains on demand.
- UI check on both orgs: titles carry their env; no `ecommerce_*` workspace `modifiedAt` changed.

---

### Total Effort Estimate

| Scale | Meaning |
|---|---|
| S | A few hours |
| M | 1–3 days |
| L | 1–2 weeks |
| XL | More than a sprint — consider splitting the feature |

Per component: S × 8 (C1, C2, C3, C5, C7, C10, C12, C13 — C13 is documentation only), M × 7 (C4, C6, C8, C9, C11, C14, C15), L × 0.

**Overall:** **L — about 2–3 weeks**, inside the spec's `l` appetite with all four environments. The projector drops from L to M (one tree, no child JSON), and the live proof from L to M (one DP). The remaining risk is calendar, not size: the AI Usecases token and that org's workspace cap gate steps 9–11. If C11 shows gdcloud dropping an AI class rather than reformatting it, stop and re-scope (upstream fix first).

**[DECISION NEEDED]**
- **Master titles.** Recommended: `GlobalMart (DEV)`, `GlobalMart (TEST)`, `GlobalMart (PREPROD)`, and bare `GlobalMart` for `globalmart_master`, pre-created by C6. Alternative: accept gdcloud's bare `globalmart` title and skip C6(d).
- **Where the canonical datasource id/schema live** (Data Model §4): an extra key in `gd_data_product/config.env.yml` if `gd-validate` tolerates it, else module defaults in `gdcloud_bridge.py`. Recommended: the config key; fall back without further review if gdcloud rejects it.
- **`data-current` credentials on PR runs.** It needs a MotherDuck token on every PR. Recommended: a read-only MotherDuck token as a repo secret `MOTHERDUCK_TOKEN_RO`, separate from the read-write token in the Environments.

---

### Implementation Order

1. **C1 Toolchain & pin** — 3.14, gdcloud `v0.51.0`, `allow-direct-references`, `package = true`, Makefile, `.yamllint`, `.python-version`. `make dev` with `ADOPT_CI=0`; 789 tests still pass.
2. **C2 `config.yml`** — `gd-init --pull` into scratch, merge; all four environments.
3. **C3 `gdcloud_bridge.py`** + unit tests; CONTRACT module row.
4. **C4 Projector** + unit tests on `mini_globalmart`; first real run writes `gd_data_product/globalmart/`.
5. **C10 CLI surface** (`gdcloud project|bootstrap|scope`, `data ensure --check`) + `tests/test_cli.py`; CONTRACT CLI rows.
6. **C5 `TargetProfile.gdcloud_environment`** + four `gdcloud-*` profiles + `corpus_workspaces` branch; CONTRACT `TargetProfile` row.
7. **C7 `gd_plugin` checks**; `uv sync`, `gd-ci list` shows both; `gd-validate` / `gd-ci run --all` green offline.
8. **C6 Bootstrap command** + mocked tests (no live run yet).
9. **C11 Live round-trip proof** on `globalmart_spike` (user go-ahead); fold canonicalization into C4 until `diff -r` is empty.
10. **C6 live, dev + test** — rehearsal then `--apply` (user go-ahead).
11. **C12 GitHub setup, part 1** — secrets, all five Environments, labels `GM` + `TOOLING`.
12. **C8 Workflow adoption** — `gd-workflows adopt .`; confirm no 4a/5a/`org_release`; `check_ci_payload` green.
13. **C9 Project-owned workflows** — `ci.yml` additions, `globalmart_post_deploy.yml`, `data-currency.yml` retarget, `tests/test_release_wiring.py`.
14. **C12 GitHub setup, part 2** — branch protection with required checks (they exist only after 12–13 ran once).
15. **C15 dev/test end-to-end** — integration steps 3–8.
16. **C6 live, preprod + prod** — capacity check on AI Usecases first (needs the token), then `--apply`.
17. **C15 preprod/prod end-to-end** — integration steps 9–11.
18. **C13 disposition + C14 Docs/STEERING/CONTRACT/ADR 011/AGENTS.md** — final CONTRACT reconciliation and README release section.
