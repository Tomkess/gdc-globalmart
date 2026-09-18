"""Tasks 12–13 — resolution, and the assertion the predecessor lacked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.layout_io import read_tree
from globalmart.normalize import (
    DATASOURCE_ID_TOKEN,
    DATASOURCE_SCHEMA_TOKEN,
    normalize_workspace,
)
from globalmart.resolve import (
    UnresolvedLayoutError,
    assert_fully_resolved,
    audit_resolution,
    resolve_and_assert,
    resolve_placeholders,
)
from globalmart.traversal import iter_datasource_slots, iter_sql_statements

FIXTURE = Path(__file__).parent / "fixtures" / "mini_globalmart"
SOURCE_SCHEMA = "globalmart"
TARGET_DATASOURCE = "globalmart-postgres"
TARGET_SCHEMA = "public_gm"


@pytest.fixture
def normalized() -> CatalogDeclarativeWorkspaceModel:
    """A placeholder-bearing model, exactly as the committed tree would be."""
    model = read_tree(FIXTURE)
    normalize_workspace(model, datasource_schema=SOURCE_SCHEMA)
    return model


def blob(model: CatalogDeclarativeWorkspaceModel) -> str:
    return json.dumps(model.to_dict(camel_case=True))


def test_every_datasource_slot_becomes_the_target(
    normalized: CatalogDeclarativeWorkspaceModel,
) -> None:
    result = resolve_placeholders(
        normalized, datasource_id=TARGET_DATASOURCE, datasource_schema=TARGET_SCHEMA
    )

    slots = list(iter_datasource_slots(normalized))
    assert result.datasource_refs_resolved == len(slots)
    assert all(slot.get() == TARGET_DATASOURCE for slot in slots)
    assert DATASOURCE_ID_TOKEN not in blob(normalized)


def test_schema_is_substituted_not_stripped(
    normalized: CatalogDeclarativeWorkspaceModel,
) -> None:
    """Stripping the placeholder produced SQL querying an unqualified table name."""
    before = {s.dataset_id: s.get() for s in iter_sql_statements(normalized)}

    resolve_placeholders(
        normalized, datasource_id=TARGET_DATASOURCE, datasource_schema=TARGET_SCHEMA
    )

    for slot in iter_sql_statements(normalized):
        statement = slot.get()
        assert DATASOURCE_SCHEMA_TOKEN not in statement
        assert f"{TARGET_SCHEMA}." in statement
        # The schema was replaced, not removed: the statement kept its qualification.
        assert len(statement) == len(before[slot.dataset_id]) + (
            len(TARGET_SCHEMA) - len(DATASOURCE_SCHEMA_TOKEN)
        ) * before[slot.dataset_id].count(DATASOURCE_SCHEMA_TOKEN)


def test_round_trip_restores_the_source_values(
    normalized: CatalogDeclarativeWorkspaceModel,
) -> None:
    """normalize -> resolve with the capture's own profile must be the identity."""
    original = read_tree(FIXTURE)
    expected = {s.dataset_id: s.get() for s in iter_sql_statements(original)}

    resolve_placeholders(
        normalized, datasource_id="globalmart-motherduck", datasource_schema=SOURCE_SCHEMA
    )

    assert {s.dataset_id: s.get() for s in iter_sql_statements(normalized)} == expected


def test_the_predecessor_bug_is_caught(normalized: CatalogDeclarativeWorkspaceModel) -> None:
    """The exact failure that shipped: a datasource id that is neither token nor target.

    The predecessor's `raw.replace('"globalmart-postgres"', ...)` was a no-op because the
    layout carried `globalmart-motherduck`. Nothing raised, and a workspace shipped pointing
    at the wrong warehouse. Here the assertion names every stale path.
    """
    for slot in iter_datasource_slots(normalized):
        slot.set("globalmart-motherduck")

    with pytest.raises(UnresolvedLayoutError) as excinfo:
        assert_fully_resolved(normalized, datasource_id=TARGET_DATASOURCE)

    message = str(excinfo.value)
    assert "globalmart-motherduck" in message
    assert TARGET_DATASOURCE in message


def test_unresolved_token_in_an_unenumerated_field_is_caught(
    normalized: CatalogDeclarativeWorkspaceModel,
) -> None:
    """The safety net: a placeholder somewhere no generator looks at."""
    normalized.analytics.metrics[0].description = "See {{ datasource_schema }} for details"

    resolve_placeholders(
        normalized, datasource_id=TARGET_DATASOURCE, datasource_schema=TARGET_SCHEMA
    )

    with pytest.raises(UnresolvedLayoutError) as excinfo:
        assert_fully_resolved(normalized, datasource_id=TARGET_DATASOURCE)
    assert "unresolved placeholder" in str(excinfo.value)


def test_unknown_placeholder_shape_is_still_caught(
    normalized: CatalogDeclarativeWorkspaceModel,
) -> None:
    """A future token nobody has defined yet must not slip through."""
    normalized.analytics.metrics[0].description = "{{ some_future_token }}"

    resolve_placeholders(
        normalized, datasource_id=TARGET_DATASOURCE, datasource_schema=TARGET_SCHEMA
    )

    with pytest.raises(UnresolvedLayoutError):
        assert_fully_resolved(normalized, datasource_id=TARGET_DATASOURCE)


def test_clean_resolution_passes_the_assertion(
    normalized: CatalogDeclarativeWorkspaceModel,
) -> None:
    result = resolve_and_assert(
        normalized, datasource_id=TARGET_DATASOURCE, datasource_schema=TARGET_SCHEMA
    )

    assert result.datasource_refs_resolved > 0
    assert result.unresolved_paths == []
    assert result.foreign_datasource_ids == {}


def test_audit_reports_without_raising(normalized: CatalogDeclarativeWorkspaceModel) -> None:
    """A caller may want to report problems before deciding to fail."""
    unresolved, foreign = audit_resolution(normalized, datasource_id=TARGET_DATASOURCE)

    assert foreign == {DATASOURCE_ID_TOKEN: len(list(iter_datasource_slots(normalized)))}
    assert unresolved, "the un-resolved model should still carry placeholders"


def test_resolution_is_idempotent(normalized: CatalogDeclarativeWorkspaceModel) -> None:
    resolve_and_assert(
        normalized, datasource_id=TARGET_DATASOURCE, datasource_schema=TARGET_SCHEMA
    )
    snapshot = blob(normalized)

    resolve_placeholders(
        normalized, datasource_id=TARGET_DATASOURCE, datasource_schema=TARGET_SCHEMA
    )

    assert blob(normalized) == snapshot
