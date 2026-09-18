"""Task 19 — warehouse adapters, loud failure, and secret hygiene."""

from __future__ import annotations

import dataclasses

import pytest
from gooddata_sdk import CatalogDataSourceMotherDuck, CatalogDataSourcePostgres

from globalmart.config import GlobalmartError, TargetProfile, WarehouseType
from globalmart.datasource import (
    DataSourceOutcome,
    UnsupportedWarehouseError,
    build_data_source,
    ensure_data_source,
)

SECRET = "super-secret-value-do-not-leak"


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
        datasource_database="gd_demo",
        datasource_secret_env="TEST_WAREHOUSE_SECRET",
    )
    base.update(overrides)
    return TargetProfile(**base)  # type: ignore[arg-type]


def test_motherduck_profile_builds_motherduck_datasource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_WAREHOUSE_SECRET", SECRET)
    ds = build_data_source(_profile())

    assert isinstance(ds, CatalogDataSourceMotherDuck)
    assert ds.id == "globalmart-motherduck"
    assert ds.schema == "globalmart"


def test_postgres_profile_builds_postgres_datasource(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_WAREHOUSE_SECRET", SECRET)
    ds = build_data_source(
        _profile(
            warehouse_type=WarehouseType.POSTGRES,
            datasource_id="globalmart-postgres",
            datasource_url="jdbc:postgresql://db:5432/globalmart",
            datasource_username="globalmart",
        )
    )

    assert isinstance(ds, CatalogDataSourcePostgres)
    assert ds.id == "globalmart-postgres"


def test_unsupported_warehouse_fails_loudly() -> None:
    """Silence here is indistinguishable from success until a chart fails much later."""
    profile = dataclasses.replace(_profile(), warehouse_type=None)

    with pytest.raises(UnsupportedWarehouseError) as excinfo:
        build_data_source(profile)
    assert "motherduck" in str(excinfo.value)


def test_postgres_without_its_secret_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_WAREHOUSE_SECRET", raising=False)

    with pytest.raises(GlobalmartError) as excinfo:
        build_data_source(
            _profile(warehouse_type=WarehouseType.POSTGRES, datasource_username="gm")
        )
    assert "TEST_WAREHOUSE_SECRET" in str(excinfo.value)


def test_secret_never_appears_in_repr_or_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A leaked warehouse password in a report or traceback would be a real incident."""
    monkeypatch.setenv("TEST_WAREHOUSE_SECRET", SECRET)

    md = build_data_source(_profile())
    assert SECRET not in repr(md)

    profile = _profile()
    assert SECRET not in repr(profile)
    # The profile carries the env var NAME, never the value.
    assert profile.datasource_secret_env == "TEST_WAREHOUSE_SECRET"


def test_rehearsal_writes_nothing(fake_sdk, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("TEST_WAREHOUSE_SECRET", SECRET)

    outcome = ensure_data_source(fake_sdk, _profile(), apply=False)

    assert outcome == DataSourceOutcome.SKIPPED_NO_APPLY
    assert fake_sdk.writes() == []


def test_apply_creates_then_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_WAREHOUSE_SECRET", SECRET)
    from tests.conftest import FakeSdk

    absent = FakeSdk(existing_datasource=False)
    assert ensure_data_source(absent, _profile(), apply=True) == DataSourceOutcome.CREATED

    present = FakeSdk(existing_datasource=True)
    assert ensure_data_source(present, _profile(), apply=True) == DataSourceOutcome.UPDATED
