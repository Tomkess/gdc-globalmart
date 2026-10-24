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
from globalmart.publish import (
    PARENT_WORKSPACE_NAME,
    resolved_workspace_id,
)
from globalmart.publish import publish_workspace as _publish_workspace

from .conftest import MINI, MINI_CANONICAL, FakeSdk, committed_mini

FIXTURE = MINI


def publish_workspace(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    """The real publish, with the mini fixture's canonical data source unless a test says otherwise."""
    kwargs.setdefault("canonical", MINI_CANONICAL)
    return _publish_workspace(*args, **kwargs)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _warehouse_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_WAREHOUSE_SECRET", "s")


def _profile(tmp_path: Path, **overrides: object) -> TargetProfile:
    base = dict(
        name="demo-cloud",
        host="https://example.gooddata.com",
        token="tok",
        organization_id="gm-ddebmti",
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
    return committed_mini()


# --- the safety gate --------------------------------------------------------


def test_apply_defaults_to_false() -> None:
    """Pinned so the safe default cannot be flipped by a later refactor."""
    assert inspect.signature(_publish_workspace).parameters["apply"].default is False


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

    result = publish_workspace(sdk, _model(), _profile(tmp_path), workspace_id="globalmart", apply=True)

    assert result.backup_path is None


def test_backup_is_written_when_content_exists(tmp_path: Path) -> None:
    """The layout a publish replaces exists nowhere else, so it is captured first."""
    sdk = FakeSdk(existing_workspace=_model())

    result = publish_workspace(sdk, _model(), _profile(tmp_path), workspace_id="globalmart", apply=True)

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


# --- the data source rewrite happens on the way out ---------------------------


def test_published_model_carries_the_target_datasource(tmp_path: Path) -> None:
    """A matching profile publishes the tree unchanged: the rewrite is a no-op."""
    sdk = FakeSdk()
    model = _model()

    result = publish_workspace(sdk, model, _profile(tmp_path), workspace_id="globalmart", apply=True)

    import json

    blob = json.dumps(model.to_dict(camel_case=True))
    assert "{{" not in blob
    assert "globalmart-motherduck" in blob
    assert result.resolve is not None and result.resolve.is_noop


def test_a_non_canonical_profile_gets_its_own_data_source(tmp_path: Path) -> None:
    """ADR 011 Stage B: canonical id and schema are rewritten to the profile's on the way out."""
    import json

    from globalmart.traversal import iter_sql_statements, iter_table_schema_slots

    sdk = FakeSdk()
    model = _model()
    profile = _profile(
        tmp_path,
        name="demo-cloud-rebuild",
        datasource_id="globalmart-rebuild",
        datasource_schema="gm_rebuild",
    )

    result = publish_workspace(sdk, model, profile, workspace_id="globalmart", apply=True)

    blob = json.dumps(model.to_dict(camel_case=True))
    assert MINI_CANONICAL.datasource_id not in blob
    assert "globalmart-rebuild" in blob
    assert {slot.get() for slot in iter_table_schema_slots(model)} == {"gm_rebuild"}
    assert all("gm_rebuild." in slot.get() for slot in iter_sql_statements(model))
    assert result.resolve is not None and not result.resolve.is_noop
    assert result.resolve.datasource_refs_rewritten > 0
    plan = "\n".join(result.summary_lines())
    assert "globalmart-motherduck / globalmart -> globalmart-rebuild / gm_rebuild" in plan


def test_the_rewrite_shows_in_a_rehearsal_and_writes_nothing(tmp_path: Path) -> None:
    sdk = FakeSdk()
    profile = _profile(tmp_path, datasource_id="globalmart-rebuild", datasource_schema="gm_rebuild")

    result = publish_workspace(sdk, _model(), profile, workspace_id="globalmart")

    assert sdk.writes() == []
    assert any("->" in line for line in result.summary_lines() if "data source rewrite" in line)


def test_a_foreign_data_source_is_refused_before_any_write(tmp_path: Path) -> None:
    """The canonical pair is the only one the rewrite touches; anything else stops the publish."""
    from globalmart.gdcloud_bridge import CanonicalDataSource
    from globalmart.resolve import UnresolvedLayoutError

    sdk = FakeSdk()
    wrong = CanonicalDataSource(datasource_id="not-what-the-tree-carries", datasource_schema="globalmart")

    with pytest.raises(UnresolvedLayoutError):
        publish_workspace(
            sdk,
            _model(),
            _profile(tmp_path, datasource_id="globalmart-rebuild"),
            workspace_id="globalmart",
            canonical=wrong,
            apply=True,
        )

    assert "put_declarative_workspace" not in sdk.writes()


def test_a_raw_capture_is_refused(tmp_path: Path) -> None:
    """A model with audit fields (not gd-store's form) would be rejected by the target with a 400."""
    from globalmart.preflight import PortabilityError

    sdk = FakeSdk()

    with pytest.raises(PortabilityError):
        publish_workspace(sdk, read_tree(FIXTURE), _profile(tmp_path), workspace_id="globalmart")

    assert sdk.writes() == []
