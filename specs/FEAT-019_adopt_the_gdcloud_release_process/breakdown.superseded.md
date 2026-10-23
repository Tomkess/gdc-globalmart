---

## Technical Breakdown — FEAT-019: Adopt the gdcloud release process (Services-MIC-Cloud parity, ecommerce-demo ADR 001/002)

Inputs: `spec.md`, `specs/STEERING.md`, `specs/CONTRACT.md`, ecommerce ADR 001 (four envs on two orgs, workspace-separated) and ADR 002 (org kinds belong to a separate org repo), ecommerce FEAT-003 `breakdown.md` (the reference decomposition), gdcloud `docs/configuration.md`, `docs/plugins.md`, `gdcloud/org_config/kinds.py`, `README.md`, and `Services-MIC-Cloud/config.yml`.

What the reference material establishes, and how it shapes this design:

- **gdcloud releases files and does not derive them.** `gd-store` writes a live workspace into `gd_data_product/<dp>/{ldm,analytics_model}/`. `gd-upload` (called by workflows 3/4/5) puts that tree into `environments.<env>.data_products.<dp>.master_workspace_id`. Nothing in gdcloud knows that 12 of GlobalMart's 13 DPs are a closure-plus-prune of the 13th. The five plugin groups (`ci_checks`, `tagging_rules`, `sql_views`, `tagging_hooks`, `metadata_docs`) are validation and metadata hooks only. None of them runs during a deploy.
- **STEERING forbids routine capture-from-live.** The rules are "The repo is the source of truth, never a live org" and "An export-from-live step is not part of any routine workflow (only a one-time bootstrap)". A routine *publish parent → split → publish domains → gd-store ×13* loop would make a live dev workspace the hop that every change passes through. That breaks the rule. This design therefore uses `gd-store` only for the one-time bootstrap and the equivalence proof. The routine path is an **offline projection**: the splitter's committed output is written straight into the gdcloud layout and gated by `--check`, just as `split --check` gates `generated/` today.
- **The data plane does not depend on the environment.** Every profile in `config/targets.yaml` reads the same MotherDuck database (`gd_demo`, schema `globalmart`), including the AI Usecases org. "Data before domains" is therefore one warehouse precondition for all four environments, not a step per environment.
- **Knowledge documents are not a release kind.** `RELEASE_KINDS` holds `agents`, `themes`, `colorPalettes` and `exportTemplates` only. ADR 009/010's corpus publish stays project-owned, and it has to run *after* gdcloud has created or updated each environment's workspaces.
- **AI Usecases host.** It is already known here: `https://usecases-ai.demo.cloud.gooddata.com`, org `w2r-kigdm6`. Only its token is missing, which is the same blocker ecommerce FEAT-005 has.
- **Existing CI.** `ci.yml` runs `normalize --check`, `domains validate --strict`, `split --check`, `data verify`, `datefilters bind --check`, `knowledge build --check` and the corpus gates. `data-currency.yml` runs a scheduled `data ensure`. `knowledge-retrieval.yml` runs scheduled retrieval against demo-cloud. All three are project-owned and stay.

---

### Components

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|
| **C0. Fit spike (gate for everything below)** | A throwaway branch that answers three questions on the parent and one domain (`sales`) before any code is written. (1) Does `uv sync` resolve with `requires-python >=3.14`, `gooddata-sdk==1.75.0` and the `gdcloud` pin together? Check which `gooddata-sdk` gdcloud requires. (2) Does a `gd-upload` → `gd-store` round trip carry every object class the parent has: `memory_items`, `parameters`, `attribute_hierarchy_objects`, `analytical_dashboard_extensions`, `analytical_dashboards/export_definitions`, and 4 WDFs? (3) Does gdcloud accept snake DP IDs with `_` labels (`GM_SALES`)? Output: a short findings note in `specs/FEAT-019.../spike.md` that resolves D3/D4/D5 | New (spike) | M |
| **C1. Toolchain & gdcloud pin** | In `pyproject.toml`: add `"gdcloud @ git+https://github.com/gooddata/gd-cloud-tooling.git@v0.51.0"` (ecommerce's decided pin), set `requires-python = ">=3.14"` and `[tool.mypy] python_version = "3.14"`, add `[tool.uv] package = true`, and add the entry point `[project.entry-points."gdcloud.ci_checks"] globalmart = "gd_plugin.checks:CHECKS"`. Add `gd_plugin` to `[tool.hatch.build.targets.wheel] packages`. Add new files `.python-version` (`3.14`), `Makefile` (MIC targets `dev`, `adopt`, `store`, `upload`, `validate`, `ci`, `format`, `lint`, `help`, plus a project target `project` that runs C4), `.yamllint`, and `.gitignore` entries `gd_output/`. The extras `data` and `agents` must still resolve on 3.14 | Existing (modify) + new files | M |
| **C2. Root `config.yml`** | Four environments on two hosts, a 13-entry `data_products` catalog, `primary_data_product: globalmart`, `default_git_branch: main`, `sql_dialect: duckdb`, and an `automation` block with `org_release` and `organization_snapshot` hard-off. Bootstrapped by `gd-init --pull` into a scratch dir, then merged by hand (shape in Data Model §3). preprod/prod blocks are committed only once the AI Usecases token exists | New | S |
| **C3. `gdcloud_bridge.py`** | A new module owned by FEAT-019, and the only module in `src/globalmart/` that reads `config.yml`. `dp_id_for(domain_key) -> str`, `parent_dp_id() -> str`, `load_release_config(path) -> ReleaseConfig`, `master_workspace_ids(env) -> dict[str, str]` (DP id → workspace id), `release_scope_from_tags(env, since) -> ReleaseScope`. It reads YAML directly rather than calling gdcloud's `get_config_value`, so the `globalmart` package keeps no runtime import of gdcloud (gdcloud stays a CI/tooling dependency) | New | S |
| **C4. Projector — `globalmart gdcloud project`** | The design core. It is offline and deterministic, and it makes the splitter's output the gdcloud-managed content of each child. It loads the parent with `read_tree(layouts/workspaces/globalmart/)` and each child with `read_model_json(generated/workspaces/globalmart-<domain>.json)`. It resolves placeholder tokens to the **gdcloud canonical values** (Data Model §5) through `resolve.resolve_placeholders` with a synthetic `TargetProfile`, then `assert_fully_resolved`. It writes `gd_data_product/<dp>/{ldm,analytics_model}/` and `workspace_data_filters.json` (none by default, D5) using the same per-object YAML writer `gd-store` uses (gdcloud's public writer if `gdcloud` exports one, otherwise `store_to_disk` + `gd-format-yaml`). It deletes stale files in each DP dir. Flags: `--domains-file`, `--layout`, `--generated`, `--out` (default `gd_data_product`), `--only`, `--dry-run`, `--check`. `--check` exits non-zero when the committed tree differs from the projection. It never reads a live org | New (`gdcloud_project.py`) | L |
| **C5. `TargetProfile.gdcloud_environment` + four profiles** | `config.py` gains `gdcloud_environment: str \| None = None`. When it is set, every workspace ID that a project-owned command touches (`knowledge-docs publish/verify`, `verify`, `data ensure` preflight) resolves through `gdcloud_bridge.master_workspace_ids(env)` instead of `domains.yaml`'s `workspace_id`. In `knowledge_docs.corpus_workspaces`, the one branch point is `profile.gdcloud_environment is not None`. `config/targets.yaml` gains `gdcloud-dev`, `gdcloud-test`, `gdcloud-preprod` and `gdcloud-prod` (Data Model §6). CONTRACT amended in the same commit | Existing (modify `config.py`, `knowledge_docs.py`, `verification.py`) | M |
| **C6. Environment bootstrap — `globalmart gdcloud bootstrap`** | Live, and gated by `--apply` (ADR 002). For one `--environment`: (a) a collision audit that lists the org's workspaces and data sources and fails if any ID in this env's plan exists *and* is not GlobalMart's, meaning its title does not start with `GlobalMart` or its ID is not in the plan; it also fails if any planned ID starts with `ecommerce_` or another known demo prefix. (b) `datasource.ensure_data_source` for `gdc_ds_globalmart_motherduck`. (c) Pre-creates the 13 masters with environment-labelled titles through `catalog_workspace.create_or_update`, because gdcloud titles a self-created master with the bare DP id and never renames it (ecommerce FEAT-003 finding). Backup before any overwrite, using `backup.backup_workspace`. Flags `--environment` (req), `--only`, `--apply` | New (`gdcloud_bootstrap.py`) | M |
| **C7. `gd_plugin/` checks** | Registered through `gdcloud.ci_checks` and run by `gd-ci` in `check_ci_checks.yml`. `derived_current`: runs C4's projection in memory for each `globalmart_*` DP and fails if `gd_data_product/<dp>/` differs. This makes a hand edit, or a workflow 2a store into a derived DP, a red build (STEERING: "Hand-editing a generated file is a defect"). `org_scope`: fails if `automation.org_release.enabled` or `automation.organization_snapshot.enabled` is truthy, or if `gd_organization/` or `gd_organization_snapshot/` exists. `id_prefix`: every catalog DP id, every `master_workspace_id` and every dataset `dataSourceId` under `gd_data_product/` must start with `globalmart` / `gdc_ds_globalmart_`. `CHECKS` exported from `gd_plugin/checks/__init__.py`, with `source="gd_plugin"` | New | M |
| **C8. Workflow adoption** | `uv run gd-workflows adopt .` via `make dev`. Expected payload: `1__create_branch_and_workspace`, `1b__delete_branch_and_workspace`, `2a__update_branch__from_workspace`, `2b__update_workspace__from_branch`, `3__automated_deployment_dev_main`, `4_manual_deployment_test`, `5_manual_deployment_prod`, `6_version_comparison`, `check_*`, `auto_gdcloud_pin`, `branch_gate`, `pr_path_gate`, plus vendored actions/scripts and `.github/gdcloud-ci.version`. With `org_release.enabled: false`, there is no `4a_*`, `5a_*`, `org_release.yml` or `auto_org_snapshot.yml`. Nothing is hand-edited. `workflows.check_ci_checks.additional_paths` widens the gate to `layouts/`, `generated/`, `config/domains.yaml` and `gd_plugin/`, so a parent-only change still triggers `gd-ci` | New (generated) | M |
| **C9. Project-owned release workflows** | Hand-written, project-owned, and placed beside the generated payload, never inside it. (a) `ci.yml` (existing) gains `globalmart gdcloud project --check` after `split --check`, plus a job `data-current` that runs `globalmart data ensure --target gdcloud-dev --check` (read-only live, new flag, see C10). Both jobs become required status checks on `main`. Since workflow 3 only runs after a merge, they gate it. (b) `globalmart_post_deploy.yml`, on `workflow_run` of workflows 3, 4 and 5 (`types: [completed]`, only `conclusion == success`). It runs `globalmart gdcloud scope --since <run_started_at>` to read the env and DPs from the `deploy-{env}-{dp}-{ver}-{ts}` tags the run wrote. Then, per DP, it runs `globalmart knowledge-docs publish --target gdcloud-<env> --workspace-id <ws> --apply` followed by `knowledge-docs verify`. It uses the GitHub Environment matching that env, so `TOKEN_GOODDATA` is mapped to `GLOBALMART_TOKEN__GDCLOUD_<ENV>`. (c) `data-currency.yml` (existing) is retargeted from `demo-cloud-rebuild` only to also keep the `globalmart` schema behind `gdcloud-*` current | Existing (modify) + new | M |
| **C10. CLI surface additions** | Registered in `cli.py`: `globalmart gdcloud project` (C4, local), `globalmart gdcloud bootstrap` (C6, live `--apply`), `globalmart gdcloud scope` (`--environment`, `--since`, `--format {text,json}`; read-only, reads git tags only). `globalmart data ensure` gains `--check`: read-only, exits 3 when the rehearsal plan contains any write. It is the warehouse analogue of the committed-artifact `--check`, and `--check` and `--apply` are mutually exclusive. CONTRACT CLI table amended, and `tests/test_cli.py` extended | Existing (modify) + new | S |
| **C11. Live bootstrap & equivalence proof** | A one-time run on the dev org (STEERING's permitted bootstrap). C6 `--environment dev --apply`, then `gd-upload` of all 13 projected DPs, then `gd-store --data-product-id <dp> --environment dev` into a scratch copy, then `diff -r` against the committed projection. The result must be empty except for documented gdcloud canonicalization, which is folded back into C4 until the diff is empty. Then `gd-validate` and `gd-ci run --all` go green. The proof starts with the parent DP and one domain, and moves to the other 11 only after those two are clean | New (process) | L |
| **C12. GitHub setup** | Environments `develop`, `staging`, `preprod`, `production` (ecommerce's MIC names), each with `TOKEN_GOODDATA` and `MOTHERDUCK_TOKEN`. `production` gets required reviewers and a branch policy of `main` plus `hotfix/*`. Plus `production-post` for C9(b) (D8). Repo secrets `TOKEN_GITHUB_GDCLOUD` (private pin) and `TOKEN_GITHUB_ADMIN` (tag pushes). Labels: the 13 DP labels plus `TOOLING`. Branch protection on `main` with required checks: PR label, CI checks, metrics/visualizations AFM, YAML formatting, yamllint, `CI / check`, `CI / data-current` | Existing (GitHub settings) | S |
| **C13. Legacy path disposition** | Spec option (b). `config/targets.yaml` and `globalmart publish parent/domains` stay for ad hoc targets (`demo-cloud`, `demo-cloud-rebuild`, `usecases-ai`, future `local-inference` / `fresh-org`) and for the existing kebab workspaces `globalmart` / `globalmart-<domain>` that `config/agents.yaml` and the A2A/MCP orchestrator (FEAT-009/010/014) read. Those IDs are not renamed. `globalmart split` stays the authoring step. `normalize.py` stays (it still produces the placeholder form that C4 resolves). Retiring it is the Stage-B follow-on (D2). `globalmart rebuild` stays the cold-org path | Existing (document only) | S |
| **C14. Docs, STEERING, CONTRACT, ADR** | README: a release section modelled on MIC `README_VERSION_MANAGEMENT.md`, the env ↔ org ↔ workspace table, the prefix convention and its reason, a statement that org-level objects are out of scope and owned by the org repo (ADR 002), and a one-line answer on `agents.yaml`: it is workspace-scoped orchestrator config, not a GoodData org object, so it is never an `agents` release kind. STEERING: amend Python to 3.14, and add three rules: "never enable `org_release` / `organization_snapshot`", "every gdcloud ID starts with `globalmart`", and "`gd_data_product/globalmart_*` is derived; regenerate with `gdcloud project`". CONTRACT: module rows `gdcloud_bridge.py`, `gdcloud_project.py`, `gdcloud_bootstrap.py`; the `TargetProfile.gdcloud_environment` row; the CLI rows; the path rows `config.yml` and `gd_data_product/<dp>/`. New ADR `011-gdcloud-release-of-derived-domains.md` recording the projection decision. Merge the gdcloud-seeded `AGENTS.md` | Existing (modify) + new | M |
| **C15. End-to-end validation** | A scripted walkthrough on the dev org, covering label-scoped workflow 3, workflow 4 to test, isolation between envs on one org, ordering of the post-deploy knowledge step, and a parent change that ripples to the domains (Test Strategy). preprod/prod are covered once they are unblocked | New (process) | M |

---

### Data Model

#### 1. ID scheme (two shared orgs, workspace-separated)

| Object | dev (`petertomko.demo.cloud`) | test (same org) | preprod (`usecases-ai.demo.cloud`) | prod (same org) |
|---|---|---|---|---|
| Parent DP id | `globalmart` | ← | ← | ← |
| Domain DP id | `globalmart_<key>` (e.g. `globalmart_store_ops`) | ← | ← | ← |
| Master workspace | `<dp>_dev` | `<dp>_test` | `<dp>_preprod` | `<dp>_master` |
| Master title (set by C6) | `GlobalMart — <label> (DEV)` / `GlobalMart (DEV)` | `… (TEST)` | `… (PREPROD)` | `GlobalMart — <label>` |
| Feature workspace (parent only, D2) | `globalmart_dev--<suffix>` | — | — | — |
| Data source | `gdc_ds_globalmart_motherduck` → MotherDuck `gd_demo`, schema `globalmart` | ← shared | `gdc_ds_globalmart_motherduck` (created by C6) | ← shared |
| Tags | global `v1.N`, hotfix `v1.N.M`, `deploy-{env}-{dp}-{ver}-{ts}` | ← | ← | ← |

The legacy kebab workspaces `globalmart` and `globalmart-<domain>` on `gm-ddebmti` cannot collide with any ID in this table. Hyphen and underscore differ, and none of these IDs is a bare `globalmart`: the parent's dev master is `globalmart_dev`. Collisions with ecommerce are ruled out because no GlobalMart ID starts with `ecommerce_`. The `ecommerce` domain's DP is `globalmart_ecommerce`, and C7 `id_prefix` and the C6 audit both enforce this. Release labels are per-repo GitHub labels, so `ECOM` (ecommerce) and `GM_ECOM` (here) never meet. They still differ, so they stay readable in deploy summaries.

#### 2. DP catalog (13 entries, derived from `domains.yaml`)

| Domain key | DP id | Label | Legacy workspace (unchanged) |
|---|---|---|---|
| — (parent) | `globalmart` | `GM` | `globalmart` |
| `customer` | `globalmart_customer` | `GM_CUSTOMER` | `globalmart-customer` |
| `ecommerce` | `globalmart_ecommerce` | `GM_ECOM` | `globalmart-ecommerce` |
| `finance` | `globalmart_finance` | `GM_FINANCE` | `globalmart-finance` |
| `hr` | `globalmart_hr` | `GM_HR` | `globalmart-hr` |
| `inventory` | `globalmart_inventory` | `GM_INVENTORY` | `globalmart-inventory` |
| `loyalty` | `globalmart_loyalty` | `GM_LOYALTY` | `globalmart-loyalty` |
| `marketing` | `globalmart_marketing` | `GM_MARKETING` | `globalmart-marketing` |
| `product` | `globalmart_product` | `GM_PRODUCT` | `globalmart-product` |
| `real_estate` | `globalmart_real_estate` | `GM_REAL_ESTATE` | `globalmart-real-estate` |
| `risk` | `globalmart_risk` | `GM_RISK` | `globalmart-risk` |
| `sales` | `globalmart_sales` | `GM_SALES` | `globalmart-sales` |
| `store_ops` | `globalmart_store_ops` | `GM_STORE_OPS` | `globalmart-store-ops` |

`dp_id_for(key) = f"{parent_dp_id}_{key}"`. Domain keys are already snake_case, so the mapping is total and reversible. Label = `GM_` + `key.upper()`, with one exception, `ecommerce → GM_ECOM`, because the label stays recognizable next to ecommerce's `ECOM`. If C0 finds that gdcloud's label validator rejects `_`, the fallback is `GMCUSTOMER` and so on. A test asserts that the catalog equals the set derived from `domains.yaml`, so adding a domain without a catalog entry fails CI.

#### 3. Root `config.yml`

```yaml
default_git_branch: "main"
sql_dialect: duckdb                      # MotherDuck; C0 confirms gdcloud's sqlglot dialect name
github_token_variable: "TOKEN_GITHUB_ADMIN"
github_dependency_token_variable: "TOKEN_GITHUB_GDCLOUD"

# ecommerce ADR 002: org-level objects are released ONLY by the org repo.
# gd_plugin/checks/org_scope.py fails gd-ci if either becomes true. Never flip these.
automation:
  org_release:
    enabled: false
  organization_snapshot:
    enabled: false
  version_comparison:
    enabled: true
  scheduled_model_validation:
    enabled: false
  translation_source:
    enabled: false
  tag_documentation:
    enabled: false
  metadata_export:
    enabled: false

workflows:
  check_ci_checks:
    additional_paths: '^gd_plugin/|^config\.yml$|^pyproject\.toml$|^layouts/workspaces/globalmart/|^generated/workspaces/|^config/domains\.yaml$|^gd_data_product/([^/]+/)?config\.env\.yml$'

primary_data_product: "globalmart"

data_products:
  globalmart:            {label: GM}
  globalmart_customer:   {label: GM_CUSTOMER}
  globalmart_ecommerce:  {label: GM_ECOM}
  globalmart_finance:    {label: GM_FINANCE}
  globalmart_hr:         {label: GM_HR}
  globalmart_inventory:  {label: GM_INVENTORY}
  globalmart_loyalty:    {label: GM_LOYALTY}
  globalmart_marketing:  {label: GM_MARKETING}
  globalmart_product:    {label: GM_PRODUCT}
  globalmart_real_estate: {label: GM_REAL_ESTATE}
  globalmart_risk:       {label: GM_RISK}
  globalmart_sales:      {label: GM_SALES}
  globalmart_store_ops:  {label: GM_STORE_OPS}

environments:
  dev:
    host: "https://petertomko.demo.cloud.gooddata.com"
    gooddata_token_variable: "GLOBALMART_TOKEN__GDCLOUD_DEV"
    github_environment: "develop"
    data_products:
      globalmart:
        master_workspace_id: "globalmart_dev"
        delete_invalid_metrics: false        # split's verify gate owns consistency; never let a
        delete_invalid_visualizations: false # deploy silently diverge the org from git
        create_clone: false
      globalmart_customer:
        master_workspace_id: "globalmart_customer_dev"
        delete_invalid_metrics: false
        delete_invalid_visualizations: false
        create_clone: false
      # … one block per DP, same shape, all 13
  test:
    host: "https://petertomko.demo.cloud.gooddata.com"   # same org as dev
    gooddata_token_variable: "GLOBALMART_TOKEN__GDCLOUD_TEST"
    github_environment: "staging"
    data_products:
      globalmart: {master_workspace_id: "globalmart_test", create_clone: false}
      # … all 13, <dp>_test
  preprod:                                              # committed once the token exists
    host: "https://usecases-ai.demo.cloud.gooddata.com"
    gooddata_token_variable: "GLOBALMART_TOKEN__GDCLOUD_PREPROD"
    github_environment: "preprod"
    data_products:
      globalmart: {master_workspace_id: "globalmart_preprod", create_clone: false}
      # … all 13, <dp>_preprod
  prod:
    host: "https://usecases-ai.demo.cloud.gooddata.com"
    gooddata_token_variable: "GLOBALMART_TOKEN__GDCLOUD_PROD"
    github_environment: "production"
    protected: true
    data_products:
      globalmart: {master_workspace_id: "globalmart_master", create_clone: false}
      # … all 13, <dp>_master
```

The local token variable names reuse the `GLOBALMART_TOKEN__<PROFILE>` convention, so one env var serves both `gd-*` and the `globalmart --target gdcloud-<env>` profile. The committed file spells out all 13 blocks per env. The `# …` above is abbreviation in this document only. A unit test asserts that each env has exactly the catalog's DP set and the `<dp>_<suffix>` naming.

#### 4. `gd_data_product/` layout

```
gd_data_product/
  config.env.yml                       # common env layer; header only (siblings share one data source)
  config.ci_checks.yml                 # only if a stock check needs excludes (C11 decides)
  globalmart/                          # projected from layouts/workspaces/globalmart/
    ldm/datasets/*.yaml                # all datasets (225 dataSourceId refs, resolved)
    ldm/date_instances/*.yaml
    analytics_model/{analytical_dashboards,analytical_dashboard_extensions,
                     attribute_hierarchy_objects,dashboard_plugins,filter_contexts,
                     memory_items,metrics,parameters,visualization_objects}/*.yaml
  globalmart_<key>/                    # ×12, projected from generated/workspaces/globalmart-<key>.json
    ldm/…                              # pruned LDM — exactly split.py's retained datasets
    analytics_model/…                  # closure + per-domain AI channels (ai_context.py)
gd_plugin/
  __init__.py
  checks/__init__.py                   # CHECKS = [derived_current.SPEC, org_scope.SPEC, id_prefix.SPEC]
  checks/derived_current.py
  checks/org_scope.py
  checks/id_prefix.py
```

The set of `analytics_model/` subfolders is whatever gdcloud's writer emits. If C0 shows it omits a class the parent has, D5 applies.

#### 5. Projection contract (C4) — field level

| Concern | Rule |
|---|---|
| Input | Parent: `layout_io.read_tree(Path("layouts/workspaces/globalmart"))`. Child: `layout_io.read_model_json(Path(f"generated/workspaces/{domain.workspace_id}.json"))`. Never re-split in C4. `split --check` already guarantees `generated/` is current, and C4 consumes it |
| `{{ datasource_id }}` (`DATASOURCE_ID_TOKEN`) | Resolved to `gdc_ds_globalmart_motherduck` by structured traversal (`traversal.py`). Never string replacement |
| `{{ datasource_schema }}` (`DATASOURCE_SCHEMA_TOKEN`) | Resolved to `globalmart`, both in SQL statements and in `dataSourceTableId.path[0]` (`iter_table_schema_slots`). Per-env divergence, if ever needed, goes into `gd_data_product/config.env.yml` `datasource_mappings`, not into content |
| Canonical profile | `TargetProfile(name="gdcloud-canonical", datasource_id="gdc_ds_globalmart_motherduck", datasource_schema="globalmart", …)`, built in code from `config.yml`'s single canonical values. No host or org: the projected tree stays org-agnostic (Portability Contract) |
| `createdBy`/`modifiedBy` | Already stripped by `normalize`. C4 asserts they are absent |
| AI channels | Parent keeps all `memoryItems` and `parameters`. Each child carries exactly what `ai_context.py` selected, so nothing is re-filtered here |
| WDFs | `workspace_data_filters.json` emitted only if `--wdf-policy keep` was used at bootstrap. Default: none (D5 confirms) |
| Determinism | Sorted file emission. Lists are not re-sorted (`dataSourceTableId.path` is positional). Output passes `gd-format-yaml --check` |
| Staleness | Files under `gd_data_product/<dp>/{ldm,analytics_model}` that the projection does not produce are deleted (or reported under `--check`). Files outside those two folders (`config.*.yml`) are never touched |

```python
# gdcloud_project.py
@dataclass(frozen=True)
class ProjectedDataProduct:
    dp_id: str                      # "globalmart" | "globalmart_<key>"
    source: Path                    # layout dir or generated JSON
    files: dict[Path, bytes]        # relative path under gd_data_product/<dp_id>/ -> content

def project_all(manifest: DomainManifest, layout: Path, generated: Path,
                only: tuple[str, ...] = ()) -> list[ProjectedDataProduct]: ...
def write_projection(projected: list[ProjectedDataProduct], out: Path, *, dry_run: bool) -> list[Path]: ...
def diff_projection(projected: list[ProjectedDataProduct], out: Path) -> list[str]: ...   # --check, C7
class ProjectionError(GlobalmartError): ...
```

```python
# gdcloud_bridge.py
@dataclass(frozen=True)
class ReleaseConfig:
    path: Path
    parent_dp_id: str                                   # primary_data_product
    labels: dict[str, str]                              # dp_id -> label
    environments: dict[str, dict[str, str]]             # env -> {dp_id: master_workspace_id}
    hosts: dict[str, str]                               # env -> host

@dataclass(frozen=True)
class ReleaseScope:
    environment: str
    version: str                                        # "v1.N" or "v1.N.M"
    dp_ids: tuple[str, ...]                             # sorted

def load_release_config(path: Path = Path("config.yml")) -> ReleaseConfig: ...
def dp_id_for(manifest: DomainManifest, domain: Domain) -> str: ...
def master_workspace_ids(cfg: ReleaseConfig, env: str) -> dict[str, str]: ...
def release_scope_from_tags(env: str, since: datetime) -> ReleaseScope: ...   # parses deploy-{env}-{dp}-{ver}-{ts}
class ReleaseConfigError(GlobalmartError): ...
```

#### 6. `TargetProfile` growth and `config/targets.yaml` entries

| Field | Type | Added by |
|---|---|---|
| `gdcloud_environment` | `str \| None`, default `None`. YAML only. Must name an env in `config.yml`, otherwise raise at profile-load | FEAT-019 |

```yaml
  gdcloud-dev:                       # also gdcloud-test (same org); gdcloud-preprod/-prod on usecases-ai
    host: https://petertomko.demo.cloud.gooddata.com
    organization_id: gm-ddebmti
    datasource_id: gdc_ds_globalmart_motherduck
    datasource_schema: globalmart
    parent_workspace_id: globalmart_dev       # informational; ids resolve via gdcloud_environment
    warehouse_type: motherduck
    datasource_name: GlobalMart MotherDuck (gdcloud)
    datasource_url: jdbc:duckdb:md:gd_demo
    datasource_database: gd_demo
    datasource_secret_env: MOTHERDUCK_TOKEN
    data_owned: true                          # same schema demo-cloud already owns (ADR 004/008)
    knowledge_scope: workspaces               # shared org — never organization level (ADR 010)
    gdcloud_environment: dev
```

`knowledge_scope: organization` is rejected at profile-load for any profile that has `gdcloud_environment` set. Both orgs are shared, and an org-level upsert would be visible to ecommerce.

---

### Integration Points

**Content flow (authoring → release), the derived-child answer:**

```
edit layouts/workspaces/globalmart/  or  config/domains.yaml
  → globalmart split            (local; writes generated/workspaces/globalmart-<d>.json)
  → globalmart gdcloud project  (local; writes gd_data_product/{globalmart,globalmart_<key>}/)
  → commit all three trees in one PR, labelled with every DP whose dir changed
  → PR gates: ci.yml (split --check, gdcloud project --check, data-current)
              + gdcloud check_* (labels cover touched DPs, AFM, gd-ci incl. derived_current)
  → merge → workflow 3: v1.N, gd-upload of labelled DPs to <dp>_dev
  → globalmart_post_deploy.yml: knowledge-docs publish+verify into those <dp>_dev
  → workflow 4 (test), workflow 5 (preprod, then prod after approval), each followed by post_deploy
```

gdcloud owns everything from the merge onwards: tags, promotion, deploy, changelog and hotfix. GlobalMart owns everything before the merge (split + projection) and the knowledge step after each deploy. A parent change that reaches N domains touches N+1 DP dirs and therefore needs N+1 labels. That is correct: `check_pr_label` is asking the right question.

| System | Touch point | Notes / constraints |
|---|---|---|
| **gdcloud** | Pinned git dependency. `gd-init --pull` (scratch only), `gd-store` (C11 only), `gd-upload` (C11 + workflows), `gd-validate`, `gd-ci`, `gd-format-yaml`, `gd-version`, `gd-hotfix`, `gd-workflows adopt/sync`. Entry point `gdcloud.ci_checks` (C7) | No fork, no hand-edited workflow. Upstream asks to file: env-labelled master titles, and a pre/post-deploy hook group. Either one would retire C6(c) or C9(b) |
| **Splitter (FEAT-004: `split.py`, `closure.py`, `prune.py`, `verify.py`)** | Unchanged. C4 consumes its committed output | ADR 006 pull-in and pruning rules are untouched. `verify_child` stays the correctness gate. C4 adds no logic of its own about which datasets a child gets |
| **`resolve.py` / `traversal.py` (FEAT-002)** | C4 calls `resolve_placeholders` + `assert_fully_resolved` with the canonical profile | No new traversal. Any slot `resolve` misses is a FEAT-002 defect, fixed there |
| **Data (FEAT-005/013, ADR 008)** | `data ensure --check` as a required PR check, plus scheduled `data-currency.yml` | One MotherDuck schema behind all four envs, so "data before domains" means the warehouse is current before any merge can trigger workflow 3. Workflows 4/5 promote onto the same, already-current data |
| **Knowledge corpus (FEAT-015/017/018, ADR 009/010)** | `globalmart_post_deploy.yml` → `knowledge-docs publish/verify --target gdcloud-<env>` | Ordering data → domains → knowledge (FEAT-018) holds structurally: data is gated before merge, domains are deployed by 3/4/5, and knowledge runs only on `workflow_run` success of those. `tests/test_release_wiring.py` asserts that the `workflow_run.workflows` names in `globalmart_post_deploy.yml` match the `name:` of the generated 3/4/5 files, so a pin bump that renames them fails CI instead of silently skipping knowledge |
| **AI memory / parameters (in-layout)** | Travel inside `gd_data_product/<dp>/analytics_model/` | gdcloud must round-trip them (C0, D5). Otherwise `gd-upload`'s declarative PUT would wipe them on every deploy, which the Portability Contract calls a defect |
| **Org repo (ecommerce ADR 002)** | None from this repo | `org_release`/`organization_snapshot` off and guarded by C7 `org_scope`. GlobalMart has no org kinds today. Any future org object goes to the org repo by PR |
| **ecommerce repo / shared orgs** | Same hosts, same Environment names, same pin line | Coordinate only the pin and Environment names. IDs and labels cannot collide by construction (§1). C6 audit runs before every first deploy per env |
| **A2A/MCP orchestrator (FEAT-009/010/014), `config/agents.yaml`, `config/mcp-tools.json`** | None | Still points at the legacy `globalmart-<domain>` workspaces fed by `globalmart publish --target demo-cloud`. Repointing it at `<dp>_master` is a follow-on, not this feature |
| **GitHub** | Environments, secrets, labels, branch protection, tags via `TOKEN_GITHUB_ADMIN` | `GITHUB_TOKEN`-pushed tags do not trigger workflows, hence the PAT. `workflow_run` executes the default-branch copy of `globalmart_post_deploy.yml`, so a PR cannot alter it before it runs with deploy credentials |
| **CONTRACT.md** | Amended in the same commit as C3–C5/C10 | New modules, `TargetProfile.gdcloud_environment`, three CLI rows, the `data ensure --check` flag, paths `config.yml` and `gd_data_product/<dp>/` (committed, derived for `globalmart_*`) |

---

### Test Strategy

**Unit (pytest, offline, fixtures extended rather than duplicated)**
- `gdcloud_project`: on `tests/fixtures/mini_globalmart/` + `tests/fixtures/mini_domains/` (2 domains). It must project 3 DPs. No `{{ … }}` token survives (`assert_fully_resolved`). Every `dataSourceId` is `gdc_ds_globalmart_motherduck`. `dataSourceTableId.path` order is preserved. A second run is byte-identical. `--check` passes on fresh output, and fails on a hand-edited metric, on a stale extra file, and on a missing dataset. `--only` limits the output. `--dry-run` writes nothing.
- Projection equivalence: the projected child LDM dataset set equals the dataset set in `generated/…json`, and the analytics object ids are equal. This is the offline half of the spec's "byte-for-byte equivalent" AC.
- `gdcloud_bridge`: catalog ↔ `domains.yaml` agreement. Each env has exactly 13 DPs. The naming is `<dp>_{dev,test,preprod,master}`. Labels are unique and uppercase. `release_scope_from_tags` parses `deploy-dev-globalmart_store_ops-v1.7-20261022T101500` correctly; DP ids contain `_` and `-` is the separator. An unknown env raises.
- `config.py`: `gdcloud_environment` naming a missing env raises at load. `knowledge_scope: organization` + `gdcloud_environment` raises.
- `knowledge_docs.corpus_workspaces`: with a `gdcloud-test` profile it returns `<dp>_test` ids, and with `demo-cloud` the legacy kebab ids, unchanged.
- `gd_plugin` checks: `org_scope` gives fail/fail/fail/pass across enabled org_release, enabled snapshot, existing `gd_organization/`, and a clean config. `id_prefix` fails on an `ecommerce_x` DP, a foreign `dataSourceId`, and a `master_workspace_id` without the prefix. `derived_current` fails on a hand-edited `gd_data_product/globalmart_sales/` file.
- `gdcloud_bootstrap` (mocked SDK): titles per env. Rehearsal writes nothing. The audit aborts on a foreign workspace with a planned id and on an `ecommerce_` id. Backup happens before overwriting an existing master.
- `data ensure --check`: exit 0 when current, 3 when a write is planned. Combined with `--apply` it is a usage error.
- `tests/test_release_wiring.py`: generated 3/4/5 `name:` values ⊆ `globalmart_post_deploy.yml` `workflow_run.workflows`. No `4a_*`, `5a_*`, `org_release.yml` or `auto_org_snapshot.yml` in `.github/workflows/`. `ci.yml` runs `split --check` before `gdcloud project --check`.
- `tests/test_cli.py`: the new rows parse, and no command has both `--apply` and `--dry-run`.

**Static / CI gates**
- `uv run gd-validate` and `uv run gd-ci run --all` are green on all 13 DPs, and `gd-ci list` shows the three `gd_plugin` checks.
- `uv run gd-workflows adopt . --check` shows no drift, and `check_ci_payload.yml` is green.
- `gd-format-yaml --check`, `yamllint` and the existing `ci.yml` steps all stay green.

**Integration — dev org (C11 + C15, checklist in the PR description)**
1. C0 spike on `globalmart` + `globalmart_sales`: round-trip `diff -r` is empty, including `memory_items/` and `parameters/`.
2. `gdcloud bootstrap --environment dev` rehearsal, then `--apply`: 13 masters titled `(DEV)`, `gdc_ds_globalmart_motherduck` present, audit clean.
3. C11 proof for all 13: `gd-upload` → `gd-store` into scratch → `diff -r` empty. `globalmart verify --target gdcloud-dev` executes every visualization with no empty or failed results.
4. A PR that edits one `store_ops` dashboard's metric in the parent: `split` + `project` touch `globalmart/` and `globalmart_store_ops/` only. With only the `GM` label, the label check fails. With `GM` + `GM_STORE_OPS` it passes. Merge → `v1.N`, deploys exactly 2 DPs to dev, writes `deploy-dev-globalmart-…` and `deploy-dev-globalmart_store_ops-…`, then `globalmart_post_deploy` publishes knowledge into exactly those 2 workspaces, and `knowledge-docs verify` passes.
5. A `TOOLING`-only PR (README) deploys nothing, and the post-deploy job is a no-op because there are no new tags.
6. A hand edit to `gd_data_product/globalmart_hr/…/metrics/x.yaml` turns `CI / check` and `derived_current` red.
7. Isolation: capture the layouts and `modifiedAt` of all 13 `<dp>_dev`. Run workflow 4 for `v1.N` → the `<dp>_test` are updated and `deploy-test-…` tags are written. The dev captures are byte-identical. Repeat in reverse.
8. Ordering: make the warehouse stale (a dev-only `data-current` failure is simulated by pointing `gdcloud-dev` at an empty scratch schema). The PR cannot merge.

**Integration — AI Usecases org (after the token exists)**
- `gdcloud bootstrap --environment preprod|prod --apply`, then workflow 5 preprod (no approval), then workflow 5 prod (waits on `production`). Deploy tags are written, the post-deploy knowledge step runs in `production-post`, and isolation between `<dp>_preprod` and `<dp>_master` is shown as in step 7.
- `globalmart verify equivalence --target-a gdcloud-test --target-b gdcloud-preprod`: equal except for the parameterized values (Portability Contract acceptance, now across the release path).

**Manual**
- README walkthrough by someone new: they explain env ↔ org ↔ workspace, the `globalmart_*` prefix and why it exists, and run a promotion.
- UI check on both orgs: the titles carry their env, and no `ecommerce_*` workspace was touched (compare `modifiedAt` before and after).

---

### Total Effort Estimate

| Scale | Meaning |
|---|---|
| S | A few hours |
| M | 1–3 days |
| L | 1–2 weeks |
| XL | More than a sprint — consider splitting the feature |

Per component: S × 5 (C2, C3, C10, C12, C13), M × 9 (C0, C1, C5, C6, C7, C8, C9, C14, C15), L × 2 (C4 the projector, C11 the 13-DP live equivalence proof).

**Overall:** **L, at the top of the band: about 4–5 weeks.** That fits the spec's `l` appetite (2–6 weeks) only for **dev + test**. The cost is driven by 13 DPs × the round-trip proof and by C0's unknowns, not by the release machinery, which is generated. Recommendation, mirroring ecommerce FEAT-003 → FEAT-005: deliver dev/test here (all components, preprod/prod parts excluded) and split **preprod/prod rollout into FEAT-019b**. FEAT-019b is a config change, C6 for two envs, the Environments, and the C15 AI Usecases runs, about 3–4 days once the token exists. If C0 finds that gdcloud cannot round-trip AI memory/parameters (D5), the feature becomes **XL** and should stop after C0 for a re-scope rather than absorb a workaround.

**[DECISION NEEDED]**
- **D1. DP id scheme.** Recommended: snake `globalmart_<key>` for gdcloud DPs and workspaces, which are *new* IDs, while the legacy kebab `globalmart-<domain>` workspaces stay untouched. That gives zero blast radius on `agents.yaml`, `mcp-tools.json` and the orchestrator. The alternative, kebab DP ids, is possible but diverges from ecommerce/MIC and makes `{dp_id}--{suffix}` harder to read.
- **D2. Source of truth for the parent.** Recommended for this feature: **Stage A**. `layouts/workspaces/globalmart/` stays the authoring surface and `gd_data_product/` is a committed, `--check`-gated projection (C4/C7). The consequence: workflows 1/1b/2a/2b are adopted (AC) but unused, because a 2a store into `gd_data_product/globalmart/` is drift by definition. **Stage B** (follow-on): make `gd_data_product/globalmart/` the authoring surface, point `split --source` at it, retire `layouts/` and `normalize.py`, and allow feature workspaces for the parent. That needs ADR 001/STEERING amendments and was deliberately kept out of scope here.
- **D3. `gooddata-sdk` version.** GlobalMart pins `==1.75.0` (the floor for `memory_items`/`parameters`). If gdcloud requires a different exact version, either GlobalMart moves to gdcloud's version (re-run the `tests/test_sdk_floor.py` + byte-stability suite) or gdcloud is isolated in a separate tool environment (`uvx`, not a project dependency), which loses the `gd_plugin` entry point. C0 decides.
- **D4. Python 3.14.** gdcloud requires it. Recommended, as ecommerce decided: move the whole repo to 3.14 and fix the `data`/`agents` extras at the dependency level. This amends STEERING's "Python 3.11+".
- **D5. AI channels and WDFs through gdcloud.** If `gd-store`/`gd-upload` drop `memory_items`, `parameters`, `attribute_hierarchy_objects`, `analytical_dashboard_extensions` or `export_definitions`, there are three options: (a) an upstream gdcloud fix before adopting; (b) a post-deploy re-apply in C9(b) via a new `globalmart publish ai-context`; (c) stop. Recommended: (a), with (b) only as a time-boxed bridge. Separately, confirm that the 4 parent WDFs are dropped (`--wdf-policy drop`), as they are for every current target.
- **D6. Data source id.** Recommended: the new `gdc_ds_globalmart_motherduck` on both orgs, following the ADR 002 convention. It sits beside the legacy `globalmart-motherduck`, which the ad hoc profiles keep using. Alternative: reuse `globalmart-motherduck` (already collision-safe) and skip one data source per org.
- **D7. Labels.** Recommended: 13 labels (`GM` + `GM_<KEY>`), which the catalog's unique-label rule requires anyway. Accept that a parent change can need up to 13 labels on one PR. Confirm that gdcloud's validator accepts `_` (C0).
- **D8. Prod knowledge step approval.** `globalmart_post_deploy.yml` writes to prod. Either (a) it uses `production` and needs a second approval, or (b) a `production-post` Environment with the same token, no reviewers, `main`-only, triggered only by `workflow_run` of an approved deploy. Recommended: (b).
- **D9. Split preprod/prod into FEAT-019b** now, given the AI Usecases token blocker is known up front. Recommended: yes.

---

### Implementation Order

1. **C0 Fit spike.** It resolves D3/D4/D5/D7 and is a hard gate. If D5 fails, stop and re-scope.
2. **Record D1/D2/D6/D8/D9**, and write ADR `011-gdcloud-release-of-derived-domains.md`.
3. **C1 Toolchain & pin.** 3.14, the gdcloud pin, `package = true`, Makefile, `.yamllint`. `make dev` with `ADOPT_CI=0`.
4. **C2 `config.yml`** with dev + test only: `gd-init --pull` into scratch, then merge.
5. **C3 `gdcloud_bridge.py`** + its unit tests, and the CONTRACT module row.
6. **C4 Projector** + unit tests on `mini_globalmart`/`mini_domains`. First full run writes `gd_data_product/` for all 13 DPs.
7. **C10 CLI surface** (`gdcloud project|bootstrap|scope`, `data ensure --check`) + `tests/test_cli.py`, and the CONTRACT CLI rows.
8. **C5 `TargetProfile.gdcloud_environment`** + `gdcloud-dev`/`gdcloud-test` profiles + the `corpus_workspaces` branch, and the CONTRACT `TargetProfile` row.
9. **C7 `gd_plugin` checks** (`derived_current`, `org_scope`, `id_prefix`). `uv sync`, then `gd-ci list` shows them.
10. **C6 Bootstrap command**, then a dev rehearsal, then dev `--apply` (needs user go-ahead per STEERING AI Behavior).
11. **C11 Live equivalence proof.** Parent first, then `globalmart_sales`, then the remaining 11. Fold any canonicalization into C4 until the diff is empty. `gd-validate`/`gd-ci run --all` green.
12. **C12 GitHub setup, part 1.** Secrets, `develop`/`staging` Environments, 14 labels.
13. **C8 Workflow adoption.** `gd-workflows adopt .`, confirm no 4a/5a/`org_release`, and `check_ci_payload` green.
14. **C9 Project-owned workflows.** Extend `ci.yml`, add `globalmart_post_deploy.yml`, retarget `data-currency.yml`, add `tests/test_release_wiring.py`.
15. **C12 GitHub setup, part 2.** Branch protection with the required checks (they exist only after 13–14 have run once).
16. **C6 for test**, then **C15 dev/test end-to-end** (steps 1–8).
17. **C13 Legacy disposition** + **C14 Docs/STEERING/CONTRACT/AGENTS.md**.
18. **FEAT-019b (blocked on the AI Usecases token):** preprod/prod blocks in `config.yml` + `gd-workflows sync` → `gdcloud-preprod`/`gdcloud-prod` profiles → C6 for both → `preprod`, `production`, `production-post` Environments → C15 AI Usecases runs + cross-org `verify equivalence`.
