"""Tasks 14–22 — the six normalizer passes, plus idempotency.

Everything runs against ``tests/fixtures/mini_globalmart``, a trimmed real capture, so the
shapes are the ones the live org actually produces rather than ones invented to pass.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.layout_io import read_tree
from globalmart.normalize import (
    DATASOURCE_ID_TOKEN,
    DATASOURCE_SCHEMA_TOKEN,
    UnparameterizedSqlError,
    WdfPolicy,
    normalize_workspace,
)

FIXTURE = Path(__file__).parent / "fixtures" / "mini_globalmart"
SOURCE_SCHEMA = "globalmart"
SOURCE_DATASOURCE_ID = "globalmart-motherduck"


@pytest.fixture
def captured() -> CatalogDeclarativeWorkspaceModel:
    """A fresh, un-normalized model per test — the passes mutate in place."""
    return read_tree(FIXTURE)


def as_blob(model: CatalogDeclarativeWorkspaceModel) -> str:
    return json.dumps(model.to_dict(camel_case=True))


def as_payload(model: CatalogDeclarativeWorkspaceModel) -> dict[str, Any]:
    return model.to_dict(camel_case=True)


# --- pass 1: user references ------------------------------------------------


def test_fixture_starts_with_audit_metadata(captured: CatalogDeclarativeWorkspaceModel) -> None:
    """Guard: if the fixture ever loses its audit fields, pass 1's tests prove nothing."""
    blob = as_blob(captured)
    assert '"createdBy"' in blob


def test_pass_1_strips_every_user_reference(captured: CatalogDeclarativeWorkspaceModel) -> None:
    result = normalize_workspace(captured, datasource_schema=SOURCE_SCHEMA)
    blob = as_blob(result.model)

    assert '"createdBy"' not in blob
    assert '"modifiedBy"' not in blob
    assert result.user_refs_stripped > 0


def test_pass_1_strips_churning_timestamps(captured: CatalogDeclarativeWorkspaceModel) -> None:
    """createdAt/modifiedAt change on every capture and would defeat byte-stability."""
    result = normalize_workspace(captured, datasource_schema=SOURCE_SCHEMA)
    blob = as_blob(result.model)

    assert '"createdAt"' not in blob
    assert '"modifiedAt"' not in blob


# --- pass 2: datasource -----------------------------------------------------


def test_pass_2_replaces_every_datasource_reference(
    captured: CatalogDeclarativeWorkspaceModel,
) -> None:
    result = normalize_workspace(captured, datasource_schema=SOURCE_SCHEMA)
    blob = as_blob(result.model)

    assert SOURCE_DATASOURCE_ID not in blob
    assert result.datasource_refs_rewritten == len(result.model.ldm.datasets)


def test_pass_2_covers_both_table_and_sql_slots(
    captured: CatalogDeclarativeWorkspaceModel,
) -> None:
    """A SQL dataset hides its datasource in sql.dataSourceId, not dataSourceTableId."""
    result = normalize_workspace(captured, datasource_schema=SOURCE_SCHEMA)

    for dataset in result.model.ldm.datasets:
        if dataset.data_source_table_id is not None:
            assert dataset.data_source_table_id.data_source_id == DATASOURCE_ID_TOKEN
        if dataset.sql is not None:
            assert dataset.sql.data_source_id == DATASOURCE_ID_TOKEN


# --- pass 3: schema ---------------------------------------------------------


def test_pass_3_introduces_the_schema_placeholder(
    captured: CatalogDeclarativeWorkspaceModel,
) -> None:
    """Live SQL carries a hardcoded schema; the normalizer parameterises it."""
    sql_datasets = [d for d in captured.ldm.datasets if d.sql is not None]
    assert sql_datasets, "fixture must carry a SQL-backed dataset"
    assert any(f"{SOURCE_SCHEMA}." in (d.sql.statement or "") for d in sql_datasets)

    result = normalize_workspace(captured, datasource_schema=SOURCE_SCHEMA)

    for dataset in result.model.ldm.datasets:
        if dataset.sql is None:
            continue
        statement = dataset.sql.statement or ""
        assert DATASOURCE_SCHEMA_TOKEN in statement
        assert f" {SOURCE_SCHEMA}." not in statement
    assert result.sql_datasets_parameterized == len(sql_datasets)


def test_pass_3_never_strips_the_placeholder(captured: CatalogDeclarativeWorkspaceModel) -> None:
    """Stripping rather than substituting was a real predecessor defect."""
    once = normalize_workspace(captured, datasource_schema=SOURCE_SCHEMA)
    statements = [d.sql.statement for d in once.model.ldm.datasets if d.sql is not None]

    twice = normalize_workspace(once.model, datasource_schema=SOURCE_SCHEMA)
    again = [d.sql.statement for d in twice.model.ldm.datasets if d.sql is not None]

    assert statements == again
    assert all(DATASOURCE_SCHEMA_TOKEN in (s or "") for s in again)


def test_pass_3_matches_only_whole_identifiers(captured: CatalogDeclarativeWorkspaceModel) -> None:
    """A column named after the schema must survive untouched."""
    dataset = next(d for d in captured.ldm.datasets if d.sql is not None)
    dataset.sql.statement = (
        "SELECT globalmart_id, t.globalmart_flag FROM globalmart.fact_orders t"
    )

    normalize_workspace(captured, datasource_schema=SOURCE_SCHEMA)

    statement = dataset.sql.statement
    assert "globalmart_id" in statement
    assert "t.globalmart_flag" in statement
    assert f"FROM {DATASOURCE_SCHEMA_TOKEN}.fact_orders" in statement


def test_pass_3_unparameterized_sql_raises(captured: CatalogDeclarativeWorkspaceModel) -> None:
    """Silence here is how a broken SQL dataset shipped for months."""
    dataset = next(d for d in captured.ldm.datasets if d.sql is not None)
    dataset.sql.statement = "SELECT 1 FROM some_other_schema.fact_orders"

    with pytest.raises(UnparameterizedSqlError) as excinfo:
        normalize_workspace(captured, datasource_schema=SOURCE_SCHEMA)

    assert dataset.id in str(excinfo.value)


def test_pass_3_non_strict_reports_instead_of_raising(
    captured: CatalogDeclarativeWorkspaceModel,
) -> None:
    dataset = next(d for d in captured.ldm.datasets if d.sql is not None)
    dataset.sql.statement = "SELECT 1 FROM some_other_schema.fact_orders"

    result = normalize_workspace(captured, datasource_schema=SOURCE_SCHEMA, strict=False)
    assert dataset.id in result.unparameterized_sql


# --- pass 4: workspace data filters -----------------------------------------


def test_pass_4_drop_clears_references(captured: CatalogDeclarativeWorkspaceModel) -> None:
    dataset = captured.ldm.datasets[0]
    dataset.workspace_data_filter_references = [object()]  # type: ignore[list-item]

    result = normalize_workspace(captured, datasource_schema=SOURCE_SCHEMA, wdf_policy=WdfPolicy.DROP)

    assert dataset.workspace_data_filter_references == []
    assert result.wdf_refs_handled == 1


def test_pass_4_keep_retains_references(captured: CatalogDeclarativeWorkspaceModel) -> None:
    """KEEP is unused today but stays tested, so enabling RLS later is a flag flip."""
    dataset = captured.ldm.datasets[0]
    dataset.workspace_data_filter_references = [object()]  # type: ignore[list-item]

    result = normalize_workspace(captured, datasource_schema=SOURCE_SCHEMA, wdf_policy=WdfPolicy.KEEP)

    assert len(dataset.workspace_data_filter_references) == 1
    assert result.wdf_refs_handled == 1


# --- pass 5: ordering -------------------------------------------------------


def test_pass_5_sorts_datasets_and_nested_lists(
    captured: CatalogDeclarativeWorkspaceModel,
) -> None:
    result = normalize_workspace(captured, datasource_schema=SOURCE_SCHEMA)

    dataset_ids = [d.id for d in result.model.ldm.datasets]
    assert dataset_ids == sorted(dataset_ids)

    for dataset in result.model.ldm.datasets:
        attribute_ids = [a.id for a in dataset.attributes or []]
        assert attribute_ids == sorted(attribute_ids)

    metric_ids = [m.id for m in result.model.analytics.metrics]
    assert metric_ids == sorted(metric_ids)


def test_pass_5_is_order_independent(captured: CatalogDeclarativeWorkspaceModel) -> None:
    """A capture that returns objects in a different order must normalize identically."""
    shuffled = read_tree(FIXTURE)
    shuffled.ldm.datasets.reverse()
    shuffled.analytics.metrics.reverse()

    first = normalize_workspace(captured, datasource_schema=SOURCE_SCHEMA)
    second = normalize_workspace(shuffled, datasource_schema=SOURCE_SCHEMA)

    assert as_payload(first.model) == as_payload(second.model)


# --- idempotency ------------------------------------------------------------


def test_normalize_is_idempotent(captured: CatalogDeclarativeWorkspaceModel) -> None:
    once = normalize_workspace(captured, datasource_schema=SOURCE_SCHEMA)
    snapshot = as_payload(once.model)

    twice = normalize_workspace(once.model, datasource_schema=SOURCE_SCHEMA)

    assert as_payload(twice.model) == snapshot


def test_second_pass_reports_no_new_user_refs(
    captured: CatalogDeclarativeWorkspaceModel,
) -> None:
    once = normalize_workspace(captured, datasource_schema=SOURCE_SCHEMA)
    twice = normalize_workspace(once.model, datasource_schema=SOURCE_SCHEMA)

    assert once.user_refs_stripped > 0
    assert twice.user_refs_stripped == 0


def test_counts_survive_normalization(captured: CatalogDeclarativeWorkspaceModel) -> None:
    """Normalization parameterises and reorders; it must never lose an object."""
    from globalmart.counts import count_objects

    before = count_objects(captured)
    result = normalize_workspace(captured, datasource_schema=SOURCE_SCHEMA)

    assert result.counts == before


# --- task 23: credential leak guard ----------------------------------------


def test_no_credential_shaped_keys_survive(
    captured: CatalogDeclarativeWorkspaceModel, tmp_path: Path
) -> None:
    """A committed layout must never carry anything secret-shaped, however it got there."""
    from globalmart.layout_io import write_tree

    result = normalize_workspace(captured, datasource_schema=SOURCE_SCHEMA)
    destination = tmp_path / "tree"
    write_tree(result.model, destination)

    forbidden = ("token", "password", "secret", "apikey", "clientsecret", "privatekey")
    offenders: list[str] = []
    for path in destination.rglob("*.yaml"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            key = line.split(":", 1)[0].strip().lstrip("- ").lower()
            if key in forbidden:
                offenders.append(f"{path.relative_to(destination)}:{number}: {line.strip()}")

    assert offenders == [], "credential-shaped keys in the layout tree:\n" + "\n".join(offenders)
