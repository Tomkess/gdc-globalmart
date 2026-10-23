---
abandoned_at: null
abandoned_reason: null
appetite: l
blocked_at: null
blocked_by: null
confidence: medium
created: '2026-10-22'
cycle: null
depends_on: []
enables: []
goal: goal-01
id: feat-019
links: []
name: 'Adopt the gdcloud release process (Services-MIC-Cloud parity, ecommerce-demo
  ADR 001/002): GlobalMart parent + 12 domain workspaces become gdcloud data products
  released dev → test → preprod → prod on two shared orgs; org-level objects owned
  by the separate org repo'
sources: []
status: done
tags:
- cicd
- gdcloud
- release
updated: '2026-10-23'
---

> **Re-scoped 2026-10-22.** The first version of this spec released all 13 GlobalMart workspaces
> (parent + 12 domains) as gdcloud data products. The live spike then showed that the demo.cloud
> org is capped at 25 workspaces (`WorkspaceCount` entitlement, DEMO tier, children included).
> 13 DPs would have needed 26 more workspaces there. The user decided that GlobalMart is **one
> parent workspace**: the 12-domain split was a one-time demo. Its 12 workspaces were backed up and
> deleted from demo.cloud the same day, and they stay in the repo as locally deployable artifacts.
> The frontmatter `name` predates this re-scope.

## Summary
GlobalMart publishes itself today with a hand-written CLI (`globalmart publish`) and one profile
per org in `config/targets.yaml`. There are no versions, no promotion gate, no PR-scoped deploys
and no staging. `gd-ecommerce-demo` deploys to the same two orgs and has adopted
**gd-cloud-tooling (`gdcloud`)**, reproducing `Services-MIC-Cloud`'s four-environment process
(dev → test → preprod → prod) on two orgs, separated by workspace ID (its ADR 001). It also keeps
org-level objects out of demo repos (its ADR 002).

This feature moves GlobalMart onto the same toolkit and process with **one data product,
`globalmart`**: the parent workspace. Responsibilities split as follows:
- **gdcloud owns:** versioning (`v1.N` tags), promotion, the generated CI payload and hotfixes.
- **GlobalMart keeps everything gdcloud has no concept of:** data generation and the warehouse load
  (ADR 008), the AI knowledge corpus publish (ADR 009/010), and the offline gates. These run as
  project-owned steps around the generated workflows.
- **The 12 domain workspaces are not released.** `domains.yaml`, `generated/workspaces/*.json` and
  the `split --check` gate stay. `globalmart publish domains --target <t> --apply` redeploys them on
  demand, and by default they use no plan slots.

## Appetite
`l` — 2–6 weeks. The scope is far smaller than the 13-DP version, so the appetite now covers all four
environments, preprod/prod included.

## Acceptance Criteria
- [ ] Given the repo, when `uv sync` / `make dev` runs, then `gdcloud` is installed from the pinned
      tag `v0.51.0` in `pyproject.toml` (ecommerce's pin) on Python 3.14, and
      `auto_gdcloud_pin.yml` keeps it current
- [ ] Given a root `config.yml`, when it is read, then it declares one data product, `globalmart`
      (label `GM`), with `primary_data_product: globalmart` and `sql_dialect: duckdb`, deployed to
      four environments, with prod `protected: true`:
      - `dev` → `globalmart_dev` and `test` → `globalmart_test`, both on `petertomko.demo.cloud`
      - `preprod` → `globalmart_preprod` and `prod` → `globalmart_master`, both on
        `usecases-ai.demo.cloud`
- [ ] Given `config.yml`, when it is read, then `automation.org_release.enabled` and
      `automation.organization_snapshot.enabled` are `false`, and a CI check fails if either
      becomes true or a `gd_organization/` folder appears (ecommerce ADR 002)
- [ ] Given the parent's authoring tree `layouts/workspaces/globalmart/` (placeholder form, ADR 001),
      when `globalmart gdcloud project` runs, then `gd_data_product/globalmart/` holds the resolved
      gdcloud layout (data source `gdc_ds_globalmart_motherduck`, schema `globalmart`), and
      `--check` fails CI on a stale or hand-edited projection
- [ ] Given the projected DP, when `gd-upload` then `gd-store` round-trip it through a workspace,
      then `diff -r` is empty: memory items, parameters, attribute hierarchies, dashboard extensions
      and export definitions all survive. `gd-validate` and `gd-ci run --all` pass
- [ ] Given `uv run gd-workflows adopt .`, when it completes, then the generated payload (1, 1b, 2a,
      2b, 3, 4, 5, 6, `check_*`, `auto_*`) is in `.github/workflows/`, with no 4a, 5a,
      `org_release` or `auto_org_snapshot`. No generated file is hand-edited, and
      `check_ci_payload.yml` reports no drift
- [ ] Given a PR labeled `GM` and merged to `main`, when workflow 3 runs, then it tags `v1.N` and
      deploys `globalmart_dev`. A `TOOLING`-only PR deploys nothing
- [ ] Given a dev-deployed version, when workflows 4 and 5 run, then it promotes to test, then
      preprod (no approval), then prod (gated on `production` Environment approval), writing
      `deploy-{env}-globalmart-{ver}-{ts}` tags. Deploying one environment leaves its same-org
      sibling unchanged
- [ ] Given a successful deploy to any environment, when the project-owned post-deploy workflow
      runs, then it publishes the knowledge corpus into that environment's workspace only and
      verifies it. The order is data → workspace → knowledge (FEAT-018), and a stale warehouse
      (`data ensure --check`) blocks the merge
- [ ] Given the 12 domains, when CI runs, then `split --check` and `domains validate --strict` still
      gate `generated/`, and no gdcloud workflow creates a domain workspace. The README documents
      the on-demand redeploy command, and that the A2A/MCP demo needs it
- [ ] Given a prod defect, when `gd-hotfix` is used, then a `hotfix/*` branch cut from the last
      prod release ships as `v1.N.1`

## Scope
- Toolchain: pin `gdcloud` `v0.51.0`; require Python ≥ 3.14; set `[tool.hatch.metadata]
  allow-direct-references`, `package = true` and the `gdcloud.ci_checks` entry point; add a
  Makefile, `.yamllint` and `.python-version`
- `config.yml` with one DP and four environments on two orgs, matching ecommerce ADR 001's hosts
  and Environment names
- An offline projector, `globalmart gdcloud project`. The authoring surface stays
  `layouts/workspaces/globalmart/` (Stage A, D2), and `gd_data_product/globalmart/` is a checked
  projection of it
- Two `gd_plugin` checks: `projection_current` and `org_scope`
- Four `gdcloud-<env>` target profiles, so the project-owned commands (knowledge publish/verify,
  `verify`, `data ensure`) address `globalmart_<env>`
- A `globalmart gdcloud bootstrap` command that creates the data source and pre-creates masters
  titled per environment. It is gated by `--apply` and takes a backup first
- Project-owned workflows: `ci.yml` gains `gdcloud project --check` and `data-current`; a new
  `globalmart_post_deploy.yml` publishes knowledge after each deploy; `data-currency.yml` is
  retargeted
- GitHub setup: Environments `develop`, `staging`, `preprod`, `production` and `production-post`;
  secrets; labels `GM` and `TOOLING`; branch protection
- A new data source, `gdc_ds_globalmart_motherduck`, on both orgs (D6)
- Docs: README release section; STEERING (Python 3.14, the org-scope rule, domains are
  local-only); CONTRACT; ADR 011

## Out of Scope
- Releasing or deploying the 12 domain workspaces through gdcloud. They stay local artifacts and
  are redeployed on demand with the existing `publish domains`
- Changing the splitter, the data generator or the corpus pipeline (ADR 006/008/009/010)
- Stage B, which would make `gd_data_product/globalmart/` the authoring tree and retire `layouts/`
  and `normalize.py`. That is a follow-on
- Repointing the A2A/MCP orchestrator (`agents.yaml`, `mcp-tools.json`) at the gdcloud workspaces
- Creating the separate org repo (ecommerce ADR 002). Nothing here depends on it
- Removing the legacy `globalmart` workspace or the `demo-cloud`/`usecases-ai` profiles. They stay
  as ad hoc targets

## Key Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A `gd-store`/`gd-upload` round trip drops or rewrites AI content (memory items, parameters, …) | Low (gdcloud's source pushes the SDK's full `CatalogDeclarativeAnalytics`) | High | Live round trip of the parent on a scratch workspace before any build (task 2); fold formatting differences into the projector |
| Workspace plan caps: demo.cloud is at 13/25 after the domain cleanup; the AI Usecases cap and usage are unknown | Medium | Medium | Check `entitlements` and `collectUsage` on AI Usecases before bootstrapping preprod/prod. This feature adds 2 workspaces per org, and domains never deploy by default |
| The A2A/MCP demo is down until the domains are redeployed | Certain (accepted 2026-10-22) | Low | Document the redeploy command in the README. Repointing to the gdcloud workspaces is a follow-on |
| The post-deploy knowledge step runs out of order, or silently stops after a gdcloud pin bump renames workflows 3/4/5 | Medium | Medium | Trigger on `workflow_run` success only; a test asserts the generated `name:` values match the trigger list |
| The AI Usecases token or MotherDuck access is missing at preprod time | Medium | Medium | The user is supplying the token, and dev/test ship independently of it |
| gdcloud upstream changes break CI | Medium | Low | Pinned tag; `auto_gdcloud_pin.yml` bumps it through a PR |

## Dependencies
- **Depends on:** gdcloud `v0.51.0`; the AI Usecases token (the user is supplying it); GitHub admin
  rights (Environments, secrets, branch protection)
- **Enables:** the same release story as ecommerce on the shared orgs; a versioned, gated path that
  goal-01 can cite. Stage B and the orchestrator repoint are follow-ons

## Related Research
- `spike.md`:
  - D3/D4 resolved: gdcloud 0.51.0, sdk 1.75.0 and Python 3.14 install together, and 789 tests pass
  - D7 resolved: underscores in labels are OK, and the dialect is `duckdb`
  - D5 looks favorable from reading the code; the live round trip is still to run
  - The workspace cap is confirmed through the entitlements API
- ecommerce `specs/decisions/001` + `002`: the env ↔ org mapping, and the rule that a demo repo
  never releases org kinds
- gdcloud `utils/workspace.py`: analytics are pushed through the SDK's full
  `CatalogDeclarativeAnalytics`, and memory items replace the workspace's own by default
- gdcloud `utils/wdf.py`: with no `workspace_data_filters.json`, the WDF upload is a no-op, which
  matches GlobalMart's WDF drop policy
- The superseded 13-DP design is kept as `breakdown.superseded.md` and `tasks.superseded.md`
  (62 tasks)

## Open Questions
- AI Usecases org: what are its workspace cap and usage, and should it reuse its existing
  `motherduck-ds` or create `gdc_ds_globalmart_motherduck` (D6 says create)? Answer once the token
  is in `.env`
- Does `globalmart_dev` need the title "GlobalMart (DEV)"? gdcloud titles a master it creates with
  the bare DP id, so the bootstrap pre-creates the master to avoid that
- Does the legacy `globalmart` workspace on demo.cloud stay indefinitely as the A2A/ad hoc target,
  or retire once the orchestrator is repointed? Not blocking
