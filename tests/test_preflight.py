"""Task 22 — everything that must fail before a byte reaches the host."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from globalmart.config import MissingProfileKeyError, TargetProfile, WarehouseType
from globalmart.layout_io import read_tree
from globalmart.normalize import normalize_workspace
from globalmart.preflight import (
    OrganizationMismatchError,
    PortabilityError,
    check_organization,
    check_portability,
    check_profile,
)

FIXTURE = Path(__file__).parent / "fixtures" / "mini_globalmart"


def _profile(**overrides: object) -> TargetProfile:
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
    )
    base.update(overrides)
    return TargetProfile(**base)  # type: ignore[arg-type]


def test_missing_url_is_named_and_nothing_is_called(
    fake_sdk, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """AC #7 asserted structurally: zero calls recorded on the SDK double."""
    monkeypatch.setenv("TEST_WAREHOUSE_SECRET", "s")
    profile = dataclasses.replace(_profile(), datasource_url=None)

    with pytest.raises(MissingProfileKeyError) as excinfo:
        check_profile(profile)

    assert "datasource_url" in str(excinfo.value)
    assert fake_sdk.calls == []


def test_unset_secret_env_is_reported_as_a_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Better here than as a KeyError at PUT time, halfway through a publish."""
    monkeypatch.delenv("TEST_WAREHOUSE_SECRET", raising=False)

    with pytest.raises(MissingProfileKeyError) as excinfo:
        check_profile(_profile())
    assert "TEST_WAREHOUSE_SECRET" in str(excinfo.value)


def test_postgres_requires_a_username(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_WAREHOUSE_SECRET", "s")

    with pytest.raises(MissingProfileKeyError) as excinfo:
        check_profile(_profile(warehouse_type=WarehouseType.POSTGRES))
    assert "datasource_username" in str(excinfo.value)


def test_complete_profile_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_WAREHOUSE_SECRET", "s")
    check_profile(_profile())


def test_organization_mismatch_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard against an over-scoped token publishing over the wrong org."""
    from tests.conftest import FakeSdk

    sdk = FakeSdk(organization_id="someone-else")

    with pytest.raises(OrganizationMismatchError) as excinfo:
        check_organization(sdk, _profile())

    message = str(excinfo.value)
    assert "someone-else" in message
    assert "gm-ddebmti" in message
    assert sdk.writes() == []


def test_matching_organization_passes(fake_sdk) -> None:  # type: ignore[no-untyped-def]
    check_organization(fake_sdk, _profile())


def test_surviving_user_reference_is_caught_before_publish() -> None:
    """A foreign createdBy makes the target reject the whole layout with a generic 400."""
    model = read_tree(FIXTURE)  # un-normalized: still carries audit fields

    with pytest.raises(PortabilityError) as excinfo:
        check_portability(model)
    assert "created_by" in str(excinfo.value) or "modified_by" in str(excinfo.value)


def test_normalized_model_passes_portability() -> None:
    model = read_tree(FIXTURE)
    normalize_workspace(model, datasource_schema="globalmart")
    check_portability(model)
