"""Tasks 27-31 — orchestration, the --apply gate, idempotency, backups."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.config import TargetProfile, WarehouseType
from globalmart.layout_io import read_tree
from globalmart.normalize import normalize_workspace
from globalmart.publish import (
    PARENT_WORKSPACE_NAME,
    publish_workspace,
    resolved_workspace_id,
)

from .conftest import FakeSdk

FIXTURE = Path(__file__).parent / "fixtures" / "mini_globalmart"


@pytest.fixture(autouse=True)
def _warehouse_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_WAREHOUSE_SECRET", "s")


def _profile(tmp_path: Path, **overrides: object) -> TargetProfile:
    base = dict(
        name="demo-cloud",
        host="https://example.gooddata.com",
        token="tok",
        organization_id="petertomko",
        datasource_id="globalmart-motherduck",
        datasource_schema="globalmart",
        warehouse_type=WarehouseType.MOTHERDUCK,
        datasource_name="GlobalMart MotherDuck",
        datasource_url="jdbc:duckdb:md:gd_demo",
        datasource_secret_env="TEST_WAREHOUSE_SECRET",
        backup_dir=tmp_path / "backups",
    )
    base.update(overrides)
    return TargetProfile(**base)  # type: ignore[arg-type]


def _model() -> CatalogDeclarativeWorkspaceModel:
    model = read_tree(FIXTURE)
    normalize_workspace(model, datasource_schema="globalmart")
    return model


# --- the safety gate --------------------------------------------------------


def test_apply_defaults_to_false() -> None:
    """Pinned so the safe default cannot be flipped by a later refactor."""
    assert inspect.signature(publish_workspace).parameters["apply"].default is False


def test_rehearsal_records_zero_writes(tmp_path: Path) -> None:
    """ADR 002: without --apply nothing reaches the host, and that is asserted structurally."""
    sdk = FakeSdk()

    result = publish_workspace(sdk, _model(), _profile(tmp_path), workspace_id="globalmart")

    assert sdk.writes() == []
    assert result.applied is False


def test_rehearsal_still_reads_and_diffs(tmp_path: Path) -> None:
    """The rehearsal is useful only if it actually inspects the target."""
    sdk = FakeSdk()

    result = publish_workspace(sdk, _model(), _profile(tmp_path), workspace_id="globalmart")

    assert "get_organization" in sdk.call_names()
    assert "get_declarative_workspace" in sdk.call_names()
    assert result.diff  # a first publish diffs as "everything is new"


def test_apply_performs_the_three_writes_in_order(tmp_path: Path) -> None:
    sdk = FakeSdk()

    publish_workspace(sdk, _model(), _profile(tmp_path), workspace_id="globalmart", apply=True)

    assert sdk.writes() == [
        "create_or_update_data_source",
        "create_or_update",
        "put_declarative_workspace",
    ]


# --- idempotency ------------------------------------------------------------


def test_second_publish_reports_no_change(tmp_path: Path) -> None:
    """The FakeSdk serves back what it was given, so convergence is provable offline."""
    sdk = FakeSdk()
    profile = _profile(tmp_path)

    first = publish_workspace(sdk, _model(), profile, workspace_id="globalmart", apply=True)
    second = publish_workspace(sdk, _model(), profile, workspace_id="globalmart", apply=True)

    assert first.changed is True
    assert second.changed is False
    assert second.digest_before == second.digest_after


# --- backups ----------------------------------------------------------------


def test_backup_is_none_when_the_workspace_does_not_exist(tmp_path: Path) -> None:
    sdk = FakeSdk()

    result = publish_workspace(
        sdk, _model(), _profile(tmp_path), workspace_id="globalmart", apply=True
    )

    assert result.backup_path is None


def test_backup_is_written_when_content_exists(tmp_path: Path) -> None:
    """The layout a publish replaces exists nowhere else, so it is captured first."""
    sdk = FakeSdk(existing_workspace=_model())

    result = publish_workspace(
        sdk, _model(), _profile(tmp_path), workspace_id="globalmart", apply=True
    )

    assert result.backup_path is not None
    assert list(result.backup_path.rglob("*.yaml")), "backup tree should not be empty"


def test_rehearsal_takes_no_backup(tmp_path: Path) -> None:
    sdk = FakeSdk(existing_workspace=_model())

    result = publish_workspace(sdk, _model(), _profile(tmp_path), workspace_id="globalmart")

    assert result.backup_path is None


# --- naming and prefixes ----------------------------------------------------


def test_workspace_id_prefix_is_applied_consistently(tmp_path: Path) -> None:
    """Lets several GlobalMart copies coexist in one org for A/B eval runs."""
    sdk = FakeSdk()
    profile = _profile(tmp_path, workspace_id_prefix="eval-a-")

    result = publish_workspace(sdk, _model(), profile, workspace_id="globalmart", apply=True)

    assert result.workspace_id == "eval-a-globalmart"
    written = {"create_or_update", "put_declarative_workspace"}
    ids = {args.get("id") for name, args in sdk.calls if name in written}
    assert ids == {"eval-a-globalmart"}


def test_resolved_workspace_id_without_prefix_is_unchanged(tmp_path: Path) -> None:
    assert resolved_workspace_id(_profile(tmp_path), "globalmart") == "globalmart"


def test_display_name_defaults_to_the_content_name(tmp_path: Path) -> None:
    """The name travels with the content, not the target."""
    sdk = FakeSdk()

    publish_workspace(sdk, _model(), _profile(tmp_path), workspace_id="globalmart", apply=True)

    names = [args.get("name") for name, args in sdk.calls if name == "create_or_update"]
    assert names == [PARENT_WORKSPACE_NAME]


def test_display_name_can_be_overridden_per_call(tmp_path: Path) -> None:
    """FEAT-004 passes each domain's label from domains.yaml through this parameter."""
    sdk = FakeSdk()

    publish_workspace(
        sdk,
        _model(),
        _profile(tmp_path),
        workspace_id="globalmart-sales",
        workspace_name="GlobalMart — Sales",
        apply=True,
    )

    names = [args.get("name") for name, args in sdk.calls if name == "create_or_update"]
    assert names == ["GlobalMart — Sales"]


# --- resolution happens on the way out --------------------------------------


def test_published_model_carries_the_target_datasource(tmp_path: Path) -> None:
    sdk = FakeSdk()
    model = _model()

    publish_workspace(sdk, model, _profile(tmp_path), workspace_id="globalmart", apply=True)

    import json

    blob = json.dumps(model.to_dict(camel_case=True))
    assert "{{ datasource_id }}" not in blob
    assert "globalmart-motherduck" in blob


def test_unnormalized_model_is_refused(tmp_path: Path) -> None:
    """Publishing a model with audit fields would be rejected by the target with a 400."""
    from globalmart.preflight import PortabilityError

    sdk = FakeSdk()

    with pytest.raises(PortabilityError):
        publish_workspace(sdk, read_tree(FIXTURE), _profile(tmp_path), workspace_id="globalmart")

    assert sdk.writes() == []
