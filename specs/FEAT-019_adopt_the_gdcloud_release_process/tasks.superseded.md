## Tasks — FEAT-019: Adopt the gdcloud release process (Services-MIC-Cloud parity, ecommerce-demo ADR 001/002)

> Appetite: `l`  ·  Generated: 2026-10-22

Scope note: per breakdown's D9 (recommended, not yet confirmed), this task list delivers **dev +
test only**. preprod/prod split into a follow-on feature (`FEAT-019b`) once the AI Usecases token
exists — tasks 1–47 below are the complete dev/test deliverable; nothing here is blocked on that
token. AC #7's preprod/prod promotion is proven generically by task 44 (workflow 4 to test) and
left for FEAT-019b to extend to workflow 5.

- [x] 1. C0 spike: confirm `uv sync` resolves with `requires-python ">=3.14"`, `gooddata-sdk==1.75.0`
      and the chosen `gdcloud` pin together, on a throwaway branch. Record the resolved
      `gooddata-sdk` version gdcloud actually requires
      Pre: none
      AC: none directly — this is the gate for D3/D4
- [ ] 2. C0 spike: publish `globalmart` (parent) and `globalmart-store-ops` (one domain, already
      the smallest-risk pair per breakdown) to a scratch dev workspace, then `gd-store` them back,
      then `diff -r` against the source. Record whether `memory_items`, `parameters`,
      `attribute_hierarchy_objects`, `analytical_dashboard_extensions`, `export_definitions` and
      the 4 WDFs round-trip
      Pre: task 1 complete; a scratch workspace on `petertomko.demo.cloud.gooddata.com`
      BLOCKED 2026-10-22: demo.cloud org is at its 25-workspace plan cap (see spike.md). User
      chose to raise the org limit; re-run once it is raised. Tasks 48+ are blocked on the same cap
      AC: none directly — resolves D5 [DECISION NEEDED: if any class is dropped, stop after this
      task and re-scope per breakdown's D5 — the feature becomes XL]
- [x] 3. C0 spike: confirm gdcloud accepts an underscore in a release label (e.g. `GM_SALES`) and
      confirm its sqlglot dialect name for MotherDuck/DuckDB
      Pre: task 1 complete
      AC: none directly — resolves D7 and the `sql_dialect` value in `config.yml`
- [ ] 4. Write `specs/FEAT-019.../spike.md` summarizing tasks 1–3's findings against D3/D4/D5/D7
      Pre: tasks 1, 2, 3 complete
      AC: none directly
- [ ] 5. Write ADR `specs/decisions/011-gdcloud-release-of-derived-domains.md` recording D1 (snake
      `globalmart_<key>` DP ids, legacy kebab workspaces untouched), D2 (Stage A: `layouts/` stays
      the authoring surface, `gd_data_product/` is a checked projection), D6 (new
      `gdc_ds_globalmart_motherduck` data source) and D9 (dev/test now, preprod/prod as
      `FEAT-019b`), referencing the spike findings from task 4
      Pre: task 4 complete
      AC: none directly (D1/D2/D6 confirmed by the user 2026-10-22; D9: user is supplying the AI
      Usecases token, so preprod/prod is unblocked — record whether it stays a separate FEAT-019b)
- [ ] 6. Bump `pyproject.toml`: `requires-python = ">=3.14"`, add the `gdcloud` git dependency pin
      decided in task 1, add `[tool.uv] package = true`, add the entry point
      `[project.entry-points."gdcloud.ci_checks"] globalmart = "gd_plugin.checks:CHECKS"`, add
      `gd_plugin` to the wheel package list, add `.python-version` (`3.14`)
      Pre: task 5 complete
      AC: #1
- [ ] 7. Run `uv sync --all-extras --dev` on 3.14 and fix any dependency fallout in the `data` and
      `agents` extras
      Pre: task 6 complete
      AC: #1
- [ ] 8. Add `Makefile` (MIC-pattern targets: `dev`, `adopt`, `store`, `upload`, `validate`, `ci`,
      `format`, `lint`, `help`, plus a project target `project` that runs `globalmart gdcloud
      project`), `.yamllint`, and `.gitignore` entry `gd_output/`
      Pre: task 7 complete
      AC: #1
- [ ] 9. Update `ci.yml`'s existing steps (lint, type check, test) to run on 3.14; confirm `mypy`
      config's `python_version` is updated to `3.14`
      Pre: task 7 complete
      AC: none directly — keeps existing gates green through the toolchain bump
- [ ] 10. Scaffold `config.yml` via `gd-init --pull` into a scratch directory against the dev org,
      then hand-merge dev + test environment blocks only (host, `gooddata_token_variable`,
      `github_environment`), per breakdown Data Model §3
      Pre: task 8 complete
      AC: #2
- [ ] 11. Add the 13-entry `data_products` catalog to `config.yml` (parent `globalmart` label `GM`,
      12 domains `globalmart_<key>` with labels from breakdown Data Model §2), plus
      `primary_data_product: globalmart`, `default_git_branch: main`, `sql_dialect` (from task 3)
      Pre: task 10 complete
      AC: #3
- [ ] 12. Add the `automation` block to `config.yml` with `org_release.enabled: false` and
      `organization_snapshot.enabled: false` explicitly set (not relying on gdcloud defaults), plus
      `workflows.check_ci_checks.additional_paths` widened to cover `layouts/`, `generated/`,
      `config/domains.yaml` and `gd_plugin/`
      Pre: task 11 complete
      AC: #10
- [ ] 13. Write a unit test asserting `config.yml`'s `data_products` catalog exactly matches the
      set derived from `domains.yaml` (parent + 12 keys), so an uncovered new domain fails CI
      Pre: task 11 complete
      AC: #3
- [ ] 14. Create `src/globalmart/gdcloud_bridge.py`: `ReleaseConfig` dataclass, `load_release_config
      (path) -> ReleaseConfig`, `dp_id_for(manifest, domain) -> str` (`f"{parent}_{key}"`),
      `master_workspace_ids(cfg, env) -> dict[str, str]`
      Pre: task 12 complete
      AC: none directly — infrastructure for #4/#6/#7
- [ ] 15. Add `ReleaseScope` dataclass and `release_scope_from_tags(env, since) -> ReleaseScope` to
      `gdcloud_bridge.py`, parsing `deploy-{env}-{dp}-{ver}-{ts}` tags (DP ids contain `_`, so the
      parse must split on the known env/version/timestamp positions, not on every `-`)
      Pre: task 14 complete
      AC: none directly — infrastructure for #9
- [ ] 16. Write unit tests for `gdcloud_bridge.py`: catalog ↔ `domains.yaml` agreement, naming
      scheme `<dp>_{dev,test}`, unique uppercase labels, `release_scope_from_tags` on a DP id
      containing `_` (e.g. `globalmart_store_ops`), and an unknown env raising
      Pre: task 15 complete
      AC: #3
- [ ] 17. Update `specs/CONTRACT.md`: add the `gdcloud_bridge.py` module row (owner FEAT-019)
      Pre: task 16 complete
      AC: none directly — STEERING requires CONTRACT stay current in the same commit
- [ ] 18. Create `src/globalmart/gdcloud_project.py`: `ProjectedDataProduct` dataclass,
      `project_all(manifest, layout, generated, only=()) -> list[ProjectedDataProduct]` that reads
      the parent via `layout_io.read_tree` and each child via `layout_io.read_model_json` (never
      re-splitting — consumes `generated/` as-is)
      Pre: task 14 complete
      AC: #8
- [ ] 19. In `gdcloud_project.py`, resolve `{{ datasource_id }}` and `{{ datasource_schema }}`
      tokens against a canonical, org-agnostic `TargetProfile` (`gdc_ds_globalmart_motherduck` /
      `globalmart`) via `resolve.resolve_placeholders` + `assert_fully_resolved`, by structured
      traversal only — never string replacement
      Pre: task 18 complete
      AC: #8
- [ ] 20. Add `write_projection(projected, out, *, dry_run) -> list[Path]` to `gdcloud_project.py`:
      emits `gd_data_product/<dp_id>/{ldm,analytics_model}/` per-object YAML files (sorted file
      emission, lists not re-sorted), and deletes stale files under those two subtrees only
      Pre: task 19 complete
      AC: #4, #8
- [ ] 21. Add `diff_projection(projected, out) -> list[str]` to `gdcloud_project.py` for the
      `--check` mode
      Pre: task 20 complete
      AC: #4
- [ ] 22. Register `globalmart gdcloud project` in `cli.py` with flags `--domains-file`, `--layout`,
      `--generated`, `--out` (default `gd_data_product`), `--only`, `--dry-run`, `--check`
      Pre: task 21 complete
      AC: #4, #8
- [ ] 23. Write unit tests for `gdcloud_project.py` on `tests/fixtures/mini_globalmart/` +
      `tests/fixtures/mini_domains/`: projects 3 DPs, no `{{ }}` token survives, every
      `dataSourceId` is the canonical value, `dataSourceTableId.path` order is preserved, a second
      run is byte-identical, `--check` passes on fresh output and fails on a hand-edited file, a
      stale extra file, and a missing dataset; `--only` limits output; `--dry-run` writes nothing
      Pre: task 22 complete
      AC: #4, #8
- [ ] 24. Write a projection-equivalence test: the projected child LDM dataset set equals the
      dataset set in `generated/workspaces/globalmart-<domain>.json`, and analytics object ids
      match — the offline half of AC #8's "byte-for-byte equivalent" claim
      Pre: task 22 complete
      AC: #8
- [ ] 25. Run `globalmart gdcloud project` for real against the full `layouts/` and `generated/`
      trees, committing the first `gd_data_product/` output for all 13 DPs
      Pre: task 23, 24 complete
      AC: #4
- [ ] 26. Add `TargetProfile.gdcloud_environment: str | None = None` to `config.py`; raise at
      profile-load if it names an environment not in `config.yml`; raise at profile-load if
      `knowledge_scope: organization` is combined with a set `gdcloud_environment` (both orgs are
      shared, per ADR 010)
      Pre: task 12 complete
      AC: none directly — infrastructure for #9
- [ ] 27. Add `gdcloud-dev` and `gdcloud-test` profiles to `config/targets.yaml` per breakdown Data
      Model §6 (new data source id, `gdcloud_environment` set, `knowledge_scope: workspaces`)
      Pre: task 26 complete
      AC: none directly — infrastructure for #9
- [ ] 28. In `knowledge_docs.py`'s `corpus_workspaces`, branch on `profile.gdcloud_environment is
      not None`: resolve workspace ids via `gdcloud_bridge.master_workspace_ids` instead of
      `domains.yaml`'s `workspace_id`
      Pre: task 27 complete
      AC: #9
- [ ] 29. Write unit tests: `gdcloud_environment` naming a missing env raises; `knowledge_scope:
      organization` + `gdcloud_environment` raises; `corpus_workspaces` with a `gdcloud-test`
      profile returns `<dp>_test` ids, and with `demo-cloud` returns the unchanged legacy kebab ids
      Pre: task 28 complete
      AC: #9
- [ ] 30. Update `specs/CONTRACT.md`: `TargetProfile.gdcloud_environment` row, the `gdcloud_project`
      CLI row, `config.yml` and `gd_data_product/<dp>/` path rows
      Pre: task 29 complete
      AC: none directly — STEERING requires CONTRACT stay current in the same commit
- [ ] 31. Create `gd_plugin/checks/org_scope.py`: fails if `automation.org_release.enabled` or
      `automation.organization_snapshot.enabled` is truthy in `config.yml`, or if `gd_organization/`
      or `gd_organization_snapshot/` exists in the repo
      Pre: task 12 complete
      AC: #10
- [ ] 32. Create `gd_plugin/checks/id_prefix.py`: fails if any catalog DP id, `master_workspace_id`,
      or dataset `dataSourceId` under `gd_data_product/` does not start with `globalmart` /
      `gdc_ds_globalmart_`
      Pre: task 25 complete
      AC: #11 (supports the prefix convention the README documents)
- [ ] 33. Create `gd_plugin/checks/derived_current.py`: runs `gdcloud_project.project_all` in
      memory for each `globalmart_*` DP and fails if `gd_data_product/<dp>/` differs — a hand edit
      or a stray `gd-store` into a derived DP turns the build red
      Pre: task 25 complete
      AC: #4
- [ ] 34. Wire `gd_plugin/checks/__init__.py`'s `CHECKS` list and run `uv sync`; confirm `gd-ci list`
      shows all three checks
      Pre: tasks 31, 32, 33 complete
      AC: #4, #10, #11
- [ ] 35. Write unit tests for the three `gd_plugin` checks: `org_scope` fail/fail/fail/pass across
      enabled `org_release`, enabled snapshot, existing `gd_organization/`, and a clean config;
      `id_prefix` fails on an `ecommerce_x` DP id, a foreign `dataSourceId`, and an unprefixed
      `master_workspace_id`; `derived_current` fails on a hand-edited file under
      `gd_data_product/globalmart_sales/`
      Pre: task 34 complete
      AC: #4, #10, #11
- [ ] 36. Create `src/globalmart/gdcloud_bootstrap.py` and register `globalmart gdcloud bootstrap`
      (flags `--environment` (req), `--only`, `--apply`): a collision audit over the org's existing
      workspaces/data sources (fails on any foreign workspace sharing a planned ID, or any planned
      ID starting with `ecommerce_` or another known demo prefix), `ensure_data_source` for
      `gdc_ds_globalmart_motherduck`, and pre-creation of the 13 masters with environment-labelled
      titles (`GlobalMart (DEV)`, `GlobalMart — <label> (DEV)`), with a backup before any overwrite
      Pre: tasks 25, 27 complete
      AC: #2
- [ ] 37. Write unit tests for `gdcloud_bootstrap.py` with a mocked SDK: correct titles per env,
      rehearsal writes nothing, audit aborts on a foreign workspace and on an `ecommerce_` id,
      backup happens before overwriting an existing master
      Pre: task 36 complete
      AC: #2
- [ ] 38. Add `--check` to `globalmart data ensure`: read-only, exits 3 when the rehearsal plan
      contains any write; mutually exclusive with `--apply`
      Pre: none (existing `dataload.py`/`generate.py` module)
      AC: #9
- [ ] 39. Write unit tests for `data ensure --check`: exit 0 when current, exit 3 when a write is
      planned, and a usage error when combined with `--apply`
      Pre: task 38 complete
      AC: #9
- [ ] 40. Register `globalmart gdcloud scope` in `cli.py` (`--environment`, `--since`, `--format
      {text,json}`): read-only, wraps `gdcloud_bridge.release_scope_from_tags`
      Pre: task 15 complete
      AC: #9
- [ ] 41. Update `specs/CONTRACT.md`'s CLI surface table with the `gdcloud bootstrap`, `gdcloud
      scope` rows and the `data ensure --check` flag; extend `tests/test_cli.py` to assert no
      command carries both `--apply` and `--dry-run`
      Pre: tasks 36, 38, 40 complete
      AC: none directly — STEERING requires CONTRACT stay current in the same commit
- [ ] 42. Create GitHub Environments `develop` and `staging`, each with secrets `TOKEN_GOODDATA`
      (mapped per-env via `GLOBALMART_TOKEN__GDCLOUD_DEV`/`_TEST`) and `MOTHERDUCK_TOKEN`. Create
      repo secrets `TOKEN_GITHUB_GDCLOUD` (private pin) and `TOKEN_GITHUB_ADMIN` (tag pushes).
      Create the 13 DP labels plus `TOOLING`
      Pre: task 11 complete
      AC: #2, #6
- [ ] 43. Run `uv run gd-workflows adopt .`; confirm the generated payload (1, 1b, 2a, 2b, 3, 4, 5,
      6, `check_*`, `auto_*`, `branch_gate`, `pr_path_gate`) lands in `.github/workflows/` with
      **no** `4a_*`, `5a_*`, `org_release.yml` or `auto_org_snapshot.yml`, and `check_ci_payload.yml`
      reports no drift
      Pre: tasks 34, 42 complete
      AC: #5, #10
- [ ] 44. Write `tests/test_release_wiring.py` asserting: the generated workflow 3/4/5 `name:`
      values are a subset of what `globalmart_post_deploy.yml`'s `workflow_run.workflows` will
      reference (added task 46); no 4a/5a/`org_release`/`auto_org_snapshot` files exist in
      `.github/workflows/`; `ci.yml` runs `split --check` before `gdcloud project --check`
      Pre: task 43 complete
      AC: #5, #9, #10
- [ ] 45. Extend `ci.yml`: add a step running `globalmart gdcloud project --check` immediately after
      the existing `split --check` step, and a job `data-current` running `globalmart data ensure
      --target gdcloud-dev --check`; mark both as required status checks
      Pre: tasks 21, 38 complete
      AC: #9
- [ ] 46. Create `globalmart_post_deploy.yml`: triggered on `workflow_run` of workflows 3 and 4
      (`types: [completed]`, `conclusion == success`); runs `globalmart gdcloud scope --since
      <run_started_at>` to read env + DPs from the deploy tags, then per DP runs `globalmart
      knowledge-docs publish --target gdcloud-<env> --workspace-id <ws> --apply` followed by
      `knowledge-docs verify`
      Pre: tasks 40, 43 complete
      AC: #9
- [ ] 47. Retarget `data-currency.yml`'s scheduled `data ensure` to also keep the `globalmart`
      schema current for the `gdcloud-dev`/`gdcloud-test` targets, alongside its existing
      `demo-cloud-rebuild` target
      Pre: task 27 complete
      AC: #9

- [ ] 48. Run `gdcloud bootstrap --environment dev` as a rehearsal (no `--apply`), review the plan,
      then run it with `--apply` [DECISION NEEDED: live write — confirm with the user before
      running `--apply` per STEERING's AI Behavior rule]
      Pre: tasks 36, 42 complete
      AC: #2
- [ ] 49. Run the C11 live equivalence proof for the **parent** DP only: `gd-upload` the projected
      `gd_data_product/globalmart/` to `globalmart_dev`, then `gd-store` it back into a scratch
      copy, then `diff -r` against the committed projection; fold any gdcloud canonicalization
      difference back into `gdcloud_project.py` until the diff is empty
      Pre: task 48 complete
      AC: #4, #8
- [ ] 50. Repeat task 49 for **one domain**, `globalmart_sales`
      Pre: task 49 complete
      AC: #4, #8
- [ ] 51. Repeat task 49 for the remaining 11 domain DPs
      Pre: task 50 complete
      AC: #4, #8
- [ ] 52. Run `uv run gd-validate` and `uv run gd-ci run --all` against all 13 DPs on dev; confirm
      green, including the three `gd_plugin` checks
      Pre: task 51 complete
      AC: #4
- [ ] 53. Run `globalmart verify --target gdcloud-dev` executing every visualization in all 13
      dev workspaces with no empty or failed results
      Pre: task 52 complete
      AC: #4
- [ ] 54. Integration test: a PR editing one `store_ops` dashboard metric in the parent. Confirm
      `split` + `gdcloud project` touch only `gd_data_product/globalmart/` and
      `gd_data_product/globalmart_store_ops/`; confirm the PR fails the label-coverage check with
      only `GM`, and passes with `GM` + `GM_STORE_OPS`
      Pre: task 53 complete
      AC: #6, #11
- [ ] 55. Continue the task-54 PR: merge it, confirm workflow 3 creates the next `v1.N` tag and
      deploys exactly the 2 labeled DPs to dev, writing `deploy-dev-globalmart-…` and
      `deploy-dev-globalmart_store_ops-…` tags, and `globalmart_post_deploy.yml` then publishes
      knowledge into exactly those 2 dev workspaces, with `knowledge-docs verify` passing
      Pre: task 54 complete
      AC: #6, #9
- [ ] 56. Integration test: a `TOOLING`-only PR (e.g. a README fix) merges and deploys nothing; the
      post-deploy job is a no-op because no new deploy tags exist
      Pre: task 55 complete
      AC: #6
- [ ] 57. Integration test: hand-edit a file under `gd_data_product/globalmart_hr/.../metrics/x.yaml`
      directly (not via the parent) and confirm both `CI / check` and `derived_current` turn red
      Pre: task 53 complete
      AC: #4
- [ ] 58. Integration test — isolation: capture the layouts and `modifiedAt` of all 13 `<dp>_dev`
      workspaces, run workflow 4 to promote `v1.N` to test, confirm `<dp>_test` are updated and
      `deploy-test-…` tags are written, and confirm the dev captures are byte-identical afterward.
      Repeat in reverse (promote a newer version, confirm dev unaffected)
      Pre: task 55 complete
      AC: #7 (test-leg only; preprod/prod isolation is FEAT-019b)
- [ ] 59. Integration test — ordering: point `gdcloud-dev` at an empty scratch warehouse schema so
      `data-current` fails, and confirm the PR from task 54's pattern cannot merge
      Pre: task 45 complete
      AC: #9
- [ ] 60. Update README with the release section (modelled on MIC's
      `README_VERSION_MANAGEMENT.md`): the env ↔ org ↔ workspace table (dev/test only, noting
      preprod/prod as FEAT-019b), the `globalmart_*` prefix convention and its reason, a statement
      that org-level objects are out of scope here and owned by a separate org repo if one exists
      for these shared orgs (ecommerce ADR 002's precedent), and a one-line note that
      `config/agents.yaml` is workspace-scoped orchestrator config, never a GoodData org object
      Pre: task 51 complete
      AC: #10, #11
- [ ] 61. Amend `specs/STEERING.md`: bump "Python 3.11+" to "Python 3.14+", and add three rules:
      never enable `org_release`/`organization_snapshot`; every gdcloud-managed ID starts with
      `globalmart`; `gd_data_product/globalmart_*` is derived — regenerate with `gdcloud project`,
      never hand-edit
      Pre: task 51 complete
      AC: #10
- [ ] 62. Document the disposition of `config/targets.yaml`, `globalmart publish`, and
      `globalmart split` in the README: they stay for ad hoc targets (`demo-cloud`,
      `demo-cloud-rebuild`, `usecases-ai`, future `local-inference`/`fresh-org`) and for the
      existing kebab `globalmart`/`globalmart-<domain>` workspaces the A2A/MCP orchestrator reads;
      `split` stays the authoring step feeding `gdcloud project`
      Pre: task 60 complete
      AC: none directly — closes the spec's Open Question on targets.yaml's fate
