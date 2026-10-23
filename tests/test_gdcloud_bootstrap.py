"""FEAT-019 tasks 25–26 — preparing an environment before its first gdcloud deploy (mocked SDK)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from globalmart import gdcloud_bootstrap
from globalmart.config import DEFAULT_TARGETS_PATH, load_profile
from globalmart.gdcloud_bootstrap import (
    MASTER_TITLES,
    BootstrapError,
    Capacity,
    bootstrap_environment,
)
from globalmart.gdcloud_bridge import ReleaseConfig, load_release_config

REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeSdk:
    """Records every call; only the reads a bootstrap makes are answered."""

    def __init__(self, *, workspaces: dict[str, str], org: str = "gm-ddebmti") -> None:
        self.calls: list[tuple[str, Any]] = []
        outer = self

        class _Org:
            def get_organization(self) -> Any:
                return SimpleNamespace(id=org)

        class _Workspaces:
            def list_workspaces(self) -> list[Any]:
                return [SimpleNamespace(id=i, name=n) for i, n in workspaces.items()]

            def create_or_update(self, workspace: Any) -> None:
                outer.calls.append(("create_or_update", (workspace.id, workspace.name)))

        class _DataSources:
            def get_data_source(self, data_source_id: str) -> Any:
                raise LookupError(data_source_id)  # absent: a first bootstrap

            def create_or_update_data_source(self, data_source: Any) -> None:
                outer.calls.append(("create_or_update_data_source", data_source.id))

        self.catalog_organization = _Org()
        self.catalog_workspace = _Workspaces()
        self.catalog_data_source = _DataSources()

    def writes(self) -> list[tuple[str, Any]]:
        return self.calls


@pytest.fixture(autouse=True)
def _secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLOBALMART_TOKEN", "tok")
    monkeypatch.setenv("MOTHERDUCK_TOKEN", "md")


@pytest.fixture
def release() -> ReleaseConfig:
    return load_release_config(REPO_ROOT / "config.yml")


def _profile(env: str) -> Any:
    return load_profile(f"gdcloud-{env}", targets_path=REPO_ROOT / DEFAULT_TARGETS_PATH)


ROOM = Capacity(limit=25, used=14)
FULL = Capacity(limit=25, used=25)


def test_rehearsal_writes_nothing(release: ReleaseConfig) -> None:
    sdk = FakeSdk(workspaces={})
    report = bootstrap_environment(sdk, _profile("dev"), release, capacity=lambda p: ROOM)  # type: ignore[arg-type]
    assert sdk.writes() == []
    assert not report.created
    assert any("REHEARSAL" in line for line in report.summary_lines())


@pytest.mark.parametrize("env", ["dev", "test", "preprod", "prod"])
def test_apply_creates_the_titled_master_and_data_source(release: ReleaseConfig, env: str) -> None:
    org = "gm-ddebmti" if env in {"dev", "test"} else "w2r-kigdm6"
    sdk = FakeSdk(workspaces={}, org=org)
    report = bootstrap_environment(  # type: ignore[arg-type]
        sdk, _profile(env), release, apply=True, capacity=lambda p: ROOM
    )
    assert report.created
    assert sdk.writes() == [
        ("create_or_update_data_source", "gdc_ds_globalmart_motherduck"),
        ("create_or_update", (release.masters[env], MASTER_TITLES[env])),
    ]


def test_only_prod_has_a_plain_title() -> None:
    assert MASTER_TITLES["prod"] == "GlobalMart"
    assert all(MASTER_TITLES[e].endswith(f"({e.upper()})") for e in ("dev", "test", "preprod"))


def test_a_full_org_stops_before_any_write(release: ReleaseConfig) -> None:
    sdk = FakeSdk(workspaces={})
    with pytest.raises(BootstrapError, match="no free workspace slot"):
        bootstrap_environment(  # type: ignore[arg-type]
            sdk, _profile("dev"), release, apply=True, capacity=lambda p: FULL
        )
    assert sdk.writes() == []


def test_a_full_org_is_fine_when_the_master_exists(release: ReleaseConfig) -> None:
    sdk = FakeSdk(workspaces={"globalmart_dev": "GlobalMart (DEV)"})
    report = bootstrap_environment(  # type: ignore[arg-type]
        sdk, _profile("dev"), release, apply=True, capacity=lambda p: FULL
    )
    assert not report.created and not report.retitled
    assert sdk.writes() == [("create_or_update_data_source", "gdc_ds_globalmart_motherduck")]


def test_someone_elses_workspace_is_never_touched(release: ReleaseConfig) -> None:
    sdk = FakeSdk(workspaces={"globalmart_test": "Ecommerce scratch"})
    with pytest.raises(BootstrapError, match="not GlobalMart's"):
        bootstrap_environment(  # type: ignore[arg-type]
            sdk, _profile("test"), release, apply=True, capacity=lambda p: ROOM
        )
    assert sdk.writes() == []


def test_a_gdcloud_titled_master_is_backed_up_then_retitled(
    release: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    # gdcloud titles a master it created itself "globalmart" — ours, just badly named.
    sdk = FakeSdk(workspaces={"globalmart_dev": "globalmart"})
    order: list[str] = []
    monkeypatch.setattr(
        gdcloud_bootstrap,
        "backup_workspace",
        lambda sdk_, profile, ws: order.append(f"backup {ws}") or Path("backups/x"),
    )
    real_create = sdk.catalog_workspace.create_or_update

    def create(workspace: Any) -> None:
        order.append(f"retitle {workspace.id}")
        real_create(workspace)

    monkeypatch.setattr(sdk.catalog_workspace, "create_or_update", create)
    sdk.catalog_workspace.list_workspaces = lambda: [  # type: ignore[method-assign]
        SimpleNamespace(id="globalmart_dev", name="GlobalMart (old)")
    ]
    report = bootstrap_environment(  # type: ignore[arg-type]
        sdk, _profile("dev"), release, apply=True, capacity=lambda p: ROOM
    )
    assert report.retitled and report.backup_path == Path("backups/x")
    assert order == ["backup globalmart_dev", "retitle globalmart_dev"]


def test_wrong_org_is_refused(release: ReleaseConfig) -> None:
    sdk = FakeSdk(workspaces={}, org="someone-else")
    with pytest.raises(Exception, match="Refusing to write"):
        bootstrap_environment(  # type: ignore[arg-type]
            sdk, _profile("dev"), release, apply=True, capacity=lambda p: ROOM
        )
    assert sdk.writes() == []


def test_a_legacy_profile_is_not_a_release_target(release: ReleaseConfig) -> None:
    legacy = load_profile("demo-cloud", targets_path=REPO_ROOT / DEFAULT_TARGETS_PATH)
    with pytest.raises(BootstrapError, match="not a gdcloud release target"):
        bootstrap_environment(FakeSdk(workspaces={}), legacy, release)  # type: ignore[arg-type]
