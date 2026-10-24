"""FEAT-019 tasks 22–23 — GlobalMart's own gd-ci checks."""

from __future__ import annotations

import shutil
from importlib.metadata import entry_points
from pathlib import Path

import pytest
import yaml

from gd_plugin.checks import CHECKS
from gd_plugin.checks.org_scope import find_violations

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_checks_are_registered_through_the_entry_point() -> None:
    targets = {e.value for e in entry_points(group="gdcloud.ci_checks")}
    assert "gd_plugin.checks:CHECKS" in targets
    # projection_current retired with ADR 011 Stage B: there is no projection left to check.
    assert {spec.name for spec in CHECKS} == {"org_scope"}
    assert all(spec.source == "gd_plugin" and spec.blocking for spec in CHECKS)


# --- org_scope -----------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    shutil.copy(REPO_ROOT / "config.yml", tmp_path / "config.yml")
    return tmp_path


def _set_flag(root: Path, flag: str, value: bool) -> None:
    config = yaml.safe_load((root / "config.yml").read_text())
    config["automation"][flag]["enabled"] = value
    (root / "config.yml").write_text(yaml.safe_dump(config))


def test_the_committed_repo_is_clean() -> None:
    assert find_violations(REPO_ROOT) == []


def test_org_release_turned_on_fails(repo: Path) -> None:
    _set_flag(repo, "org_release", True)
    assert find_violations(repo) == ["config.yml automation.org_release.enabled is true"]


def test_org_snapshot_turned_on_fails(repo: Path) -> None:
    _set_flag(repo, "organization_snapshot", True)
    assert find_violations(repo) == ["config.yml automation.organization_snapshot.enabled is true"]


@pytest.mark.parametrize("folder", ["gd_organization", "gd_organization_snapshot"])
def test_an_org_tree_fails(repo: Path, folder: str) -> None:
    (repo / folder).mkdir()
    assert find_violations(repo) == [f"{folder}/ exists"]


def test_a_target_with_organization_knowledge_scope_fails(repo: Path) -> None:
    (repo / "config").mkdir()
    (repo / "config" / "targets.yaml").write_text(
        yaml.safe_dump(
            {
                "targets": {
                    "fine": {"knowledge_scope": "workspaces"},
                    "default": {"host": "https://x"},
                    "org-wide": {"knowledge_scope": "organization"},
                }
            }
        )
    )
    assert find_violations(repo) == [
        "config/targets.yaml target 'org-wide' sets knowledge_scope: organization — "
        "org-level knowledge is owned by the org repo"
    ]
