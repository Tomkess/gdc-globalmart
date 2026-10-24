"""FEAT-019 task 35 — the project-owned workflows stay wired to gdcloud's generated ones.

gdcloud regenerates its workflows on every pin bump. The post-deploy knowledge step subscribes to
them by display name, and a renamed workflow would make `workflow_run` silently never fire: the
corpus would stop reaching freshly deployed workspaces and nothing would turn red. These tests are
that red.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from globalmart.gdcloud_bridge import load_release_config

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
POST_DEPLOY = WORKFLOWS / "globalmart_post_deploy.yml"
DEPLOY_WORKFLOWS = (
    "3__automated_deployment_dev_main.yml",
    "4_manual_deployment_test.yml",
    "5_manual_deployment_prod.yml",
)


def _load(path: Path) -> dict:  # type: ignore[type-arg]
    document = yaml.safe_load(path.read_text())
    # PyYAML reads the bare key `on:` as the boolean True.
    if True in document:
        document["on"] = document.pop(True)
    return document


def test_post_deploy_subscribes_to_every_deploy_workflow_by_its_current_name() -> None:
    names = {_load(WORKFLOWS / f)["name"] for f in DEPLOY_WORKFLOWS}
    subscribed = set(_load(POST_DEPLOY)["on"]["workflow_run"]["workflows"])
    assert subscribed == names


def test_post_deploy_runs_only_after_success() -> None:
    document = _load(POST_DEPLOY)
    assert document["on"]["workflow_run"]["types"] == ["completed"]
    assert "conclusion == 'success'" in document["jobs"]["scope"]["if"]


def test_post_deploy_maps_prod_to_its_own_environment() -> None:
    # Every non-prod environment's GitHub Environment comes from config.yml via `gdcloud scope`;
    # prod's knowledge step is rerouted to production-post (D8) so it needs no second approval.
    text = POST_DEPLOY.read_text()
    assert '[ "$env" = "prod" ] && gh_env=production-post' in text
    release = load_release_config(REPO_ROOT / "config.yml")
    assert release.github_environments["prod"] == "production"


def test_no_org_level_workflow_is_installed() -> None:
    present = {path.name for path in WORKFLOWS.glob("*.yml")}
    forbidden = {name for name in present if name.startswith(("4a_", "5a_"))}
    forbidden |= present & {"org_release.yml", "auto_org_snapshot.yml"}
    assert forbidden == set()


def test_ci_gates_the_derived_trees_in_order() -> None:
    steps = [step.get("run", "") for step in _load(WORKFLOWS / "ci.yml")["jobs"]["check"]["steps"]]
    split = next(i for i, run in enumerate(steps) if "globalmart split --check" in run)
    domains = next(i for i, run in enumerate(steps) if "domains validate --strict" in run)
    # The domains stay gated though they are local-only.
    assert domains < split


def test_stage_b_retired_the_layout_gates() -> None:
    """ADR 011 Stage B: no layouts/ tree to normalize, no projection to compare."""
    runs = " ".join(step.get("run", "") for step in _load(WORKFLOWS / "ci.yml")["jobs"]["check"]["steps"])
    assert "normalize --check" not in runs
    assert "gdcloud project" not in runs


def test_gdcloud_formatting_check_gates_the_tree() -> None:
    """gd-format-yaml --check is the formatting gate for gd_data_product/, in CI and in make."""
    workflow = _load(WORKFLOWS / "check_gd_formatting_yaml.yml")
    assert workflow["name"] == "GoodData YAML Formatting Check"
    assert "gd-format-yaml" in (WORKFLOWS / "check_gd_formatting_yaml.yml").read_text()
    makefile = (REPO_ROOT / ".github" / "gdcloud.mk").read_text()
    assert "gd-format-yaml --data-product-id $(DP) --check" in makefile


def test_ci_blocks_a_merge_onto_a_stale_warehouse() -> None:
    job = _load(WORKFLOWS / "ci.yml")["jobs"]["data-current"]
    runs = " ".join(step.get("run", "") for step in job["steps"])
    assert "data ensure --target gdcloud-dev" in runs and "--check" in runs and "--apply" not in runs


def _max_age(runs: str) -> int:
    match = re.search(r"--max-age-days (\d+)", runs)
    assert match, runs
    return int(match.group(1))


def test_the_merge_gate_is_looser_than_the_refresh() -> None:
    """A gate as strict as the refresh would block every PR from the day data ages out until the next
    scheduled refresh, which only fires once the data is already past its limit."""
    gate = " ".join(s.get("run", "") for s in _load(WORKFLOWS / "ci.yml")["jobs"]["data-current"]["steps"])
    refresh = " ".join(
        s.get("run", "") for s in _load(WORKFLOWS / "data-currency.yml")["jobs"]["ensure"]["steps"]
    )
    assert _max_age(gate) >= _max_age(refresh) + 7, "the gate needs at least a week of slack"


def test_a_refresh_also_invalidates_the_other_orgs_cache() -> None:
    """Both orgs read the one schema; the second must be told after a real load, and only then."""
    jobs = _load(WORKFLOWS / "data-currency.yml")["jobs"]
    notify = jobs["notify-ai-usecases"]
    assert notify["needs"] == "ensure" and "loaded == 'true'" in notify["if"]
    assert notify["environment"] == "production-post"
    runs = " ".join(step.get("run", "") for step in notify["steps"])
    assert "data notify --target gdcloud-prod --apply" in runs
    assert jobs["ensure"]["outputs"]["loaded"] == "${{ steps.ensure.outputs.loaded }}"


def test_post_deploy_gates_date_filters_on_the_deployed_master() -> None:
    """FEAT-011 AC 6: the live two-window gate runs on what was just deployed, read-only."""
    job = _load(POST_DEPLOY)["jobs"]["datefilters"]
    assert job["needs"] == "scope"
    assert job["environment"] == "${{ needs.scope.outputs.github_environment }}"
    runs = " ".join(step.get("run", "") for step in job["steps"])
    assert "globalmart datefilters gate" in runs
    assert '--target "gdcloud-${{ needs.scope.outputs.environment }}"' in runs
    assert '--workspace-id "${{ needs.scope.outputs.workspace_id }}"' in runs
    assert "--apply" not in runs
