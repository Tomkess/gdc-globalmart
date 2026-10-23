## Tasks — FEAT-019: Adopt the gdcloud release process (one data product: globalmart)

> Appetite: `l`  ·  Generated: 2026-10-22 (re-scoped; the 13-DP list is `tasks.superseded.md`)

The following decisions were settled on 2026-10-22:

- **D1 / D2 / D6** — workspace IDs are `globalmart_{dev,test,preprod,master}`. Stage A projection. New data source `gdc_ds_globalmart_motherduck`.
- **Scope** — preprod/prod are in scope; the user supplies the AI Usecases token.
- **Titles** — `GlobalMart (DEV)` / `(TEST)` / `(PREPROD)` / `GlobalMart`, pre-created by the bootstrap.
- **Canonical data source** — the canonical data source id and schema come from a `globalmart_canonical` key in `gd_data_product/config.env.yml`. If `gd-validate` rejects that key, they fall back to defaults in `gdcloud_bridge.py`.
- **`data-current` token** — runs on the repo secret `MOTHERDUCK_TOKEN_RO`.

- [x] 1. Spike: dependencies resolve on Python 3.14 with gdcloud `v0.51.0` and `gooddata-sdk==1.75.0`. 789 tests pass. Labels and `sql_dialect: duckdb` confirmed (spike.md)
       Pre: none
       AC: #1
- [x] 2. Spike: break the only LDM reference cycle by dropping `dim_department → dim_employee` (`manager_id`) and keeping the attribute. Re-split (only `globalmart-hr.json` changes), all offline gates green, 789 tests pass
       Pre: task 1 complete
       AC: #5
- [x] 3. Spike: live round trip of the projected parent through scratch `globalmart_spike` (`gd-upload` → `gd-store`). Nothing lost: 1766 files differ in formatting only, 14 memory-item `keywords` lists differ in order only, and `workspace_data_filters.json` comes back as `{"data": []}`. Scratch workspace deleted
       Pre: task 2 complete
       AC: #5
- [x] 4. Write `specs/decisions/011-gdcloud-release-of-globalmart.md`. It records: one DP, the domains as local-only artifacts, the Stage A projection, the ID scheme, the new data source, `org_release` off, the LDM cycle fix, and the spike results
       Pre: task 3 complete
       AC: #2, #3, #10
- [x] 5. Update `pyproject.toml`: pin gdcloud `v0.51.0`, `requires-python = ">=3.14"`, mypy `python_version = "3.14"`, `[tool.uv] package = true`, `[tool.hatch.metadata] allow-direct-references = true`, the `gdcloud.ci_checks` entry point, and `gd_plugin` in the wheel packages. Add `.python-version`. Run `uv sync --all-extras --dev` and confirm 789 tests pass
       Pre: none
       AC: #1
- [x] 6. Add `Makefile` (`dev`, `adopt`, `store`, `upload`, `validate`, `ci`, `format`, `lint`, `help`, `project`, `project-check`), `.yamllint`, and `gd_output/` in `.gitignore`. Move the `ci.yml` interpreter to 3.14
       Pre: task 5 complete
       AC: #1
- [x] 7. Write `config.yml` per breakdown Data Model §2: one DP `globalmart` (label `GM`), four environments, `protected: true` on prod, `sql_dialect: duckdb`, `create_clone: false`, and the `automation` block with `org_release` and `organization_snapshot` set to `false`. Use `gd-init --pull` into a scratch dir only to compare keys
       Pre: task 5 complete
       AC: #2, #3
- [x] 8. Add `gd_data_product/config.env.yml` with `globalmart_canonical: {datasource_id: gdc_ds_globalmart_motherduck, datasource_schema: globalmart}` and run `gd-validate` against it. If gdcloud rejects the unknown key, remove it and record the fallback to code defaults in ADR 011
       Pre: task 7 complete
       AC: #4
- [x] 9. Create `src/globalmart/gdcloud_bridge.py` with `ReleaseConfig`, `load_release_config`, `master_workspace_id`, and `ReleaseConfigError`. It raises when there is not exactly one DP, an environment lacks the DP, or a master ID is not `globalmart_<suffix>`. It reads the canonical data source from task 8's location
       Pre: task 8 complete
       AC: #2
- [x] 10. Add `ReleaseScope` and `release_scope_from_tags(env, since, *, repo)` to `gdcloud_bridge.py`. It parses `deploy-{env}-globalmart-{ver}-{ts}` (including hotfix `v1.N.M`) and returns `None` when no tag is newer than `since`
       Pre: task 9 complete
       AC: #9
- [x] 11. Write unit tests for `gdcloud_bridge.py`: it loads the committed `config.yml`; there is one DP labelled `GM`; masters are `globalmart_{dev,test,preprod,master}`; host pairs dev/test and preprod/prod match; `prod.protected` is set; tag parsing works, including hotfix and the `None` case; an unknown environment raises
       Pre: task 10 complete
       AC: #2, #9
- [x] 12. Create `src/globalmart/gdcloud_project.py` with `Projection`, `project_parent`, and `ProjectionError`. It reads `layouts/workspaces/globalmart/` with `read_tree`, resolves placeholders against the canonical data source via `resolve_placeholders` and `assert_fully_resolved`, and asserts there are no `createdBy`/`modifiedBy` fields
       Pre: task 9 complete
       AC: #4
- [x] 13. Add `write_projection` and `diff_projection` to `gdcloud_project.py`. They emit `gd_data_product/globalmart/{ldm,analytics_model}/` in gdcloud's YAML style (`gd-format-yaml` output) and `workspace_data_filters.json` = `{"data": []}`, as the spike showed. They delete stale files inside the two content folders only and never touch `config.*.yml`
       Pre: task 12 complete
       AC: #4
- [x] 14. Register `globalmart gdcloud project` in `cli.py` with `--layout`, `--out`, `--dry-run`, and `--check`
       Pre: task 13 complete
       AC: #4
- [x] 15. Write unit tests for the projector on `tests/fixtures/mini_globalmart/`. Cover: no `{{ }}` placeholder survives; every `dataSourceId` is canonical; `dataSourceTableId.path` order is preserved; a second run is byte-identical; `--check` fails on a hand edit, a stale extra file, and a missing dataset; `--dry-run` writes nothing; `config.env.yml` is untouched
       Pre: task 14 complete
       AC: #4
- [x] 16. Run `globalmart gdcloud project` on the real tree and commit `gd_data_product/globalmart/`. Confirm `gd-format-yaml --check` is clean
       Pre: task 15 complete
       AC: #4
- [x] 17. Register `globalmart gdcloud scope` (`--environment`, `--since` (required), `--format {text,json}`; read-only, wraps `release_scope_from_tags`) and add `--check` to `globalmart data ensure` (exit 3 when a write is planned; mutually exclusive with `--apply`)
       Pre: task 10 complete
       AC: #9
- [x] 18. Write unit tests for `data ensure --check`: exit 0 when the data is current, exit 3 when a write is planned, and a usage error when combined with `--apply`
       Pre: task 17 complete
       AC: #9
- [x] 19. Add `TargetProfile.gdcloud_environment` to `config.py`. Raise at profile-load when it names an environment missing from `config.yml`, when `parent_workspace_id` differs from that environment's master, or when it is combined with `knowledge_scope: organization`
       Pre: task 9 complete
       AC: #9
- [x] 20. Add the `gdcloud-dev`, `gdcloud-test`, `gdcloud-preprod`, and `gdcloud-prod` profiles to `config/targets.yaml` (breakdown Data Model §5). Branch `knowledge_docs.corpus_workspaces` so that when `gdcloud_environment` is set it returns only `(parent_workspace_id,)`
       Pre: task 19 complete
       AC: #9
- [x] 21. Write unit tests: each of the three profile-load errors raises; all four `gdcloud-*` profiles load; `corpus_workspaces` returns `("globalmart_test",)` for `gdcloud-test` even with `--domains-file`, and is unchanged for `demo-cloud`
       Pre: task 20 complete
       AC: #9
- [x] 22. Create `gd_plugin/checks/org_scope.py` and `gd_plugin/checks/projection_current.py`, and export `CHECKS` from `gd_plugin/checks/__init__.py`. Run `uv sync` and confirm `gd-ci list` shows both
       Pre: tasks 13, 16 complete
       AC: #3, #4
- [x] 23. Write unit tests for the `gd_plugin` checks. `org_scope` fails, fails, fails, then passes across: `org_release` on, snapshot on, `gd_organization/` present, clean config. `projection_current` fails on a hand edit under `gd_data_product/globalmart/`
       Pre: task 22 complete
       AC: #3, #4
- [x] 24. Run `gd-validate` and `gd-ci run --all` offline against the committed projection and fix any findings in the projector, never in the projected files
       Pre: task 23 complete
       AC: #5
- [x] 25. Create `src/globalmart/gdcloud_bootstrap.py` and register `globalmart gdcloud bootstrap` (`--environment` required, `--apply`, `--no-backup`). It runs four steps, in order:
       (a) a capacity check comparing the `entitlements` `WorkspaceCount` against `collectUsage` (raw REST; note the SDK gap in a comment)
       (b) a collision audit that fails on a foreign-titled master
       (c) `ensure_data_source` for `gdc_ds_globalmart_motherduck`
       (d) pre-creating the master with its environment title, taking a backup before any overwrite
       Pre: tasks 9, 20 complete
       AC: #2
- [x] 26. Write unit tests for the bootstrap (mocked SDK and REST): the rehearsal writes nothing; titles are correct per environment; the capacity check fails at the cap and passes when the master already exists; the audit aborts on a foreign-titled `globalmart_test`; the backup runs before an overwrite
       Pre: task 25 complete
       AC: #2
- [x] 27. Update `specs/CONTRACT.md`. Add module rows for `gdcloud_bridge.py`, `gdcloud_project.py`, and `gdcloud_bootstrap.py`, and the `TargetProfile.gdcloud_environment` row. Add CLI rows for `gdcloud project`, `gdcloud bootstrap`, `gdcloud scope`, and `data ensure --check`. Add path rows for `config.yml`, `gd_data_product/globalmart/`, and `gd_plugin/`. Extend `tests/test_cli.py` (new rows parse; no command has both `--apply` and `--dry-run`)
       Pre: tasks 14, 17, 21, 25 complete
       AC: none directly — STEERING requires CONTRACT to change in the same commit
- [x] 28. Live: run `gdcloud bootstrap --environment dev` and `--environment test` as a rehearsal, then with `--apply`. Expect `GlobalMart (DEV)` / `(TEST)` to exist, the data source to be present, and demo.cloud at 16/25 [DECISION NEEDED: live write — confirm with the user before `--apply`]
       Pre: tasks 26, 27 complete; `MOTHERDUCK_TOKEN` set in `.env`
       AC: #2, #8
- [x] 29. Live: `gd-upload --environment dev`, then `globalmart verify --target gdcloud-dev --workspace globalmart_dev`. Every visualization executes and none is empty
       Pre: task 28 complete
       AC: #5
- [x] 30. Create GitHub Environments `develop`, `staging`, `preprod`, `production` (required reviewers; branches `main` and `hotfix/*`), and `production-post` (`main` only, no reviewers), each with `TOKEN_GOODDATA` and `MOTHERDUCK_TOKEN`. Create repo secrets `TOKEN_GITHUB_GDCLOUD`, `TOKEN_GITHUB_ADMIN`, and `MOTHERDUCK_TOKEN_RO`, and labels `GM` and `TOOLING`
       DONE 2026-10-23: `TOKEN_GITHUB_GDCLOUD`/`TOKEN_GITHUB_ADMIN` are the user's gh CLI token (their choice — re-login rotates it, CI then needs both secrets re-set). No read-only MotherDuck token exists yet, so `MOTHERDUCK_TOKEN_RO` is not created; task 32 uses `MOTHERDUCK_TOKEN` until it is
       Pre: task 7 complete
       AC: #7, #8
- [x] 31. Run `uv run gd-workflows adopt .`. Confirm the 1/1b/2a/2b/3/4/5/6, `check_*`, and `auto_*` payload is present, with no 4a, 5a, `org_release.yml`, or `auto_org_snapshot.yml`, and that `check_ci_payload.yml` shows no drift
       Pre: tasks 22, 30 complete
       AC: #6
- [x] 32. Extend `ci.yml`: add `globalmart gdcloud project --check` after `split --check` (keep `split --check` and `domains validate --strict`), and add a `data-current` job running `data ensure --target gdcloud-dev --check` with `MOTHERDUCK_TOKEN` (swap to a read-only `MOTHERDUCK_TOKEN_RO` once one exists)
       Pre: tasks 16, 17 complete
       AC: #9, #10
- [x] 33. Create `globalmart_post_deploy.yml`. It triggers on `workflow_run` of the generated 3, 4, and 5, and runs only on success. `gdcloud scope` yields the environment and version, and the job exits 0 when there is no scope. It maps the environment to its GitHub Environment (prod → `production-post`), then runs `knowledge-docs publish` followed by `verify --target gdcloud-<env> --parent-only --workspace-id globalmart_<suffix> --apply`
       Pre: tasks 17, 21, 31 complete
       AC: #9
- [x] 34. Retarget `data-currency.yml` to `gdcloud-dev --apply`, with GoodData cache invalidation covering `gdc_ds_globalmart_motherduck` on both orgs (a matrix over `gdcloud-dev` and `gdcloud-prod`)
       Pre: task 20 complete
       AC: #9
- [x] 35. Write `tests/test_release_wiring.py`. Assert: the `name:` values of generated workflows 3, 4, and 5 are a subset of the post-deploy `workflow_run.workflows`; no 4a, 5a, `org_release`, or `auto_org_snapshot` workflow exists; `ci.yml` runs `split --check`, `domains validate --strict`, and `gdcloud project --check`; the post-deploy environment mapping equals `config.yml`
       Pre: tasks 32, 33 complete
       AC: #6, #9, #10
- [ ] 36. Turn on branch protection on `main` with the required checks: PR label, CI checks, AFM, YAML formatting, yamllint, `CI / check`, and `CI / data-current`
       Pre: task 35 complete, with the workflows having run once on a PR
       AC: #7
- [ ] 37. Integration: open a PR that edits one parent metric, labelled `GM`, and merge it. Expect a `v1.N` tag, `deploy-dev-globalmart-v1.N-…`, and the post-deploy job publishing and verifying the corpus in `globalmart_dev` only
       Pre: tasks 29, 36 complete
       AC: #7, #9
- [ ] 38. Integration: a `TOOLING`-only PR deploys nothing, and the post-deploy job exits 0. A hand edit under `gd_data_product/globalmart/` turns `CI / check` and `projection_current` red
       Pre: task 37 complete
       AC: #4, #7
- [ ] 39. Integration: workflow 4 promotes `v1.N` to `globalmart_test` and post-deploy runs there. Capture `globalmart_dev`'s layout and `modifiedAt` before the promotion and confirm they are byte-identical after it (isolation)
       Pre: task 37 complete
       AC: #8
- [ ] 40. Integration: simulate a stale schema with a scratch profile so that `data-current` goes red, and confirm the merge is blocked
       Pre: task 36 complete
       AC: #9
- [ ] 41. (Also: extend data-currency.yml's cache invalidation to the AI Usecases org's `gdc_ds_globalmart_motherduck` — task 34 covers demo.cloud only, because no command invalidates another org's cache without a reload.) Live, AI Usecases: once `GLOBALMART_TOKEN__GDCLOUD_PREPROD` and `_PROD` are in `.env`, run `gdcloud bootstrap --environment preprod` and `--environment prod` as a rehearsal (the capacity check shows the org's cap and usage), then with `--apply` [DECISION NEEDED: live write on the second org — confirm before `--apply`]
       Pre: tasks 26, 30 complete; AI Usecases token supplied
       AC: #2, #8
- [ ] 42. Integration: workflow 5 to preprod (no approval), then prod (waits for the `production` approval). Expect deploy tags, post-deploy to run in `production-post`, and preprod to stay unchanged by the prod deploy
       Pre: tasks 39, 41 complete
       AC: #8, #9
- [ ] 43. Integration: run `globalmart verify equivalence --target-a gdcloud-test --target-b gdcloud-preprod`. The two must be equal except for parameterized values
       Pre: task 42 complete
       AC: #8
- [ ] 44. Integration: `gd-hotfix` cuts `hotfix/*` from the last prod tag and ships `v1.N.1` to prod through `production`, without unreleased `main` changes
       Pre: task 42 complete
       AC: #11
- [ ] 45. Update the README with a release section: the environment ↔ org ↔ workspace table, the `GM`/`TOOLING` label rules, promotion and hotfix how-to, a note that org-level objects are owned by the org repo, that domains are local-only (with `publish domains --target <t> --apply`), and that the A2A/MCP demo needs those domains redeployed. Merge the gdcloud-seeded `AGENTS.md`
       Pre: task 42 complete
       AC: #3, #10
- [ ] 46. Amend `specs/STEERING.md`. Change Python 3.11+ to 3.14. Add the rules "never enable `org_release`/`organization_snapshot`", "`gd_data_product/globalmart/` is derived — regenerate with `gdcloud project`", and "domain workspaces are local-only, never released". Mark ADR 011 Accepted
       Pre: task 45 complete
       AC: #3, #10
