"""FEAT-019 tasks 19–21 — target profiles that address a gdcloud environment."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pytest
import yaml

from globalmart.cli import DEFAULT_DOMAINS_PATH, _corpus_workspaces
from globalmart.config import DEFAULT_TARGETS_PATH, GlobalmartError, load_profile
from globalmart.gdcloud_bridge import DEFAULT_ENV_CONFIG_PATH, DEFAULT_RELEASE_CONFIG_PATH

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGETS = REPO_ROOT / DEFAULT_TARGETS_PATH
RELEASE_PROFILES = {
    "gdcloud-dev": ("dev", "globalmart_dev"),
    "gdcloud-test": ("test", "globalmart_test"),
    "gdcloud-preprod": ("preprod", "globalmart_preprod"),
    "gdcloud-prod": ("prod", "globalmart_master"),
}


@pytest.fixture(autouse=True)
def _token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLOBALMART_TOKEN", "tok")


def _repo_with(tmp_path: Path, profile: dict) -> Path:  # type: ignore[type-arg]
    """A throwaway repo root holding config.yml and one target profile, `probe`."""
    (tmp_path / "config").mkdir()
    (tmp_path / "gd_data_product").mkdir()
    shutil.copy(REPO_ROOT / DEFAULT_RELEASE_CONFIG_PATH, tmp_path / "config.yml")
    shutil.copy(REPO_ROOT / DEFAULT_ENV_CONFIG_PATH, tmp_path / DEFAULT_ENV_CONFIG_PATH)
    base = yaml.safe_load(TARGETS.read_text())["targets"]["gdcloud-test"]
    targets = tmp_path / DEFAULT_TARGETS_PATH
    targets.write_text(yaml.safe_dump({"targets": {"probe": {**base, **profile}}}))
    return targets


@pytest.mark.parametrize(("name", "expected"), sorted(RELEASE_PROFILES.items()))
def test_release_profiles_load(name: str, expected: tuple[str, str]) -> None:
    profile = load_profile(name, targets_path=TARGETS)
    assert (profile.gdcloud_environment, profile.parent_workspace_id) == expected
    assert profile.datasource_id == "gdc_ds_globalmart_motherduck"
    assert profile.knowledge_scope.value == "workspaces"


def test_legacy_profiles_are_not_release_targets() -> None:
    assert load_profile("demo-cloud", targets_path=TARGETS).gdcloud_environment is None


def test_unknown_environment_raises(tmp_path: Path) -> None:
    targets = _repo_with(tmp_path, {"gdcloud_environment": "qa"})
    with pytest.raises(GlobalmartError, match="Unknown environment 'qa'"):
        load_profile("probe", targets_path=targets)


def test_parent_must_be_the_environments_master(tmp_path: Path) -> None:
    targets = _repo_with(tmp_path, {"parent_workspace_id": "globalmart"})
    with pytest.raises(GlobalmartError, match="deploys 'test' to 'globalmart_test'"):
        load_profile("probe", targets_path=targets)


def test_organization_scope_is_refused(tmp_path: Path) -> None:
    targets = _repo_with(tmp_path, {"knowledge_scope": "organization"})
    with pytest.raises(GlobalmartError, match="release orgs are shared"):
        load_profile("probe", targets_path=targets)


# --- the knowledge corpus reaches the release workspace only -------------------------------


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "workspace_id": None,
        "parent_only": False,
        "domains_file": str(REPO_ROOT / DEFAULT_DOMAINS_PATH),
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_release_target_publishes_to_its_master_only() -> None:
    profile = load_profile("gdcloud-test", targets_path=TARGETS)
    # No --parent-only, a domains file at hand: still one workspace. Domains are local-only.
    assert _corpus_workspaces(_args(), profile) == (["globalmart_test"], True)


def test_release_target_refuses_another_workspace() -> None:
    profile = load_profile("gdcloud-test", targets_path=TARGETS)
    with pytest.raises(GlobalmartError, match="releases 'globalmart_test' only"):
        _corpus_workspaces(_args(workspace_id="globalmart-sales"), profile)


def test_legacy_target_addresses_the_parent_by_default() -> None:
    """The domains are local-only (ADR 011); a deleted one used to 404 every publish."""
    profile = load_profile("demo-cloud", targets_path=TARGETS)
    assert _corpus_workspaces(_args(), profile) == (["globalmart"], False)


def test_legacy_target_reaches_every_domain_when_asked() -> None:
    profile = load_profile("demo-cloud", targets_path=TARGETS)
    workspaces, narrowed = _corpus_workspaces(_args(include_domains=True), profile)
    assert not narrowed
    assert workspaces[0] == "globalmart" and len(workspaces) == 13
