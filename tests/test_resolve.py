"""The data source rewrite on the way to an org, and the assertion the predecessor lacked.

ADR 011 Stage B: the committed tree carries the canonical data source concretely, and a publish
rewrites it to the profile's — a no-op when they match.
"""

from __future__ import annotations

import json

import pytest
from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.gdcloud_bridge import CanonicalDataSource
from globalmart.resolve import (
    UnresolvedLayoutError,
    assert_fully_resolved,
    audit_resolution,
    resolve_and_assert,
    rewrite_data_source,
)
from globalmart.traversal import iter_datasource_slots, iter_sql_statements, iter_table_schema_slots

from .conftest import MINI_CANONICAL, committed_mini

TARGET = CanonicalDataSource(datasource_id="globalmart-postgres", datasource_schema="public_gm")


@pytest.fixture
def committed() -> CatalogDeclarativeWorkspaceModel:
    """A model exactly as the committed tree holds it: canonical data source, no audit fields."""
    return committed_mini()


def blob(model: CatalogDeclarativeWorkspaceModel) -> str:
    return json.dumps(model.to_dict(camel_case=True))


def test_every_datasource_slot_becomes_the_target(committed: CatalogDeclarativeWorkspaceModel) -> None:
    result = rewrite_data_source(committed, source=MINI_CANONICAL, target=TARGET)

    slots = list(iter_datasource_slots(committed))
    assert result.datasource_refs_rewritten == len(slots) > 0
    assert all(slot.get() == TARGET.datasource_id for slot in slots)
    assert MINI_CANONICAL.datasource_id not in blob(committed)


def test_every_table_schema_becomes_the_target(committed: CatalogDeclarativeWorkspaceModel) -> None:
    result = rewrite_data_source(committed, source=MINI_CANONICAL, target=TARGET)

    schemas = [slot.get() for slot in iter_table_schema_slots(committed)]
    assert result.table_schemas_rewritten == len(schemas) > 0
    assert set(schemas) == {TARGET.datasource_schema}


def test_sql_schema_is_rewritten_as_a_dotted_identifier(committed: CatalogDeclarativeWorkspaceModel) -> None:
    """The schema is replaced as `<schema>.`, never as a bare substring."""
    before = {s.dataset_id: s.get() for s in iter_sql_statements(committed)}
    assert before, "the mini fixture should carry a SQL dataset"

    result = rewrite_data_source(committed, source=MINI_CANONICAL, target=TARGET)

    assert result.sql_statements_rewritten == len(before)
    for slot in iter_sql_statements(committed):
        statement = slot.get()
        assert f"{TARGET.datasource_schema}." in statement
        assert f"{MINI_CANONICAL.datasource_schema}." not in statement


def test_a_column_named_like_the_schema_is_left_alone() -> None:
    from globalmart.resolve import _schema_pattern

    statement = "SELECT globalmart_id, my_globalmart FROM globalmart.fact_a JOIN globalmart_rebuild.x ON 1=1"
    rewritten = _schema_pattern("globalmart").sub("other.", statement)
    assert (
        rewritten == "SELECT globalmart_id, my_globalmart FROM other.fact_a JOIN globalmart_rebuild.x ON 1=1"
    )


def test_a_matching_profile_is_a_noop(committed: CatalogDeclarativeWorkspaceModel) -> None:
    """Every gdcloud environment uses the canonical data source: nothing may change."""
    snapshot = blob(committed)

    result = resolve_and_assert(
        committed,
        canonical=MINI_CANONICAL,
        datasource_id=MINI_CANONICAL.datasource_id,
        datasource_schema=MINI_CANONICAL.datasource_schema,
    )

    assert result.is_noop
    assert blob(committed) == snapshot
    assert "none" in result.summary_lines()[0]


def test_a_rewrite_names_both_sides_in_the_plan(committed: CatalogDeclarativeWorkspaceModel) -> None:
    result = resolve_and_assert(
        committed,
        canonical=MINI_CANONICAL,
        datasource_id=TARGET.datasource_id,
        datasource_schema=TARGET.datasource_schema,
    )

    plan = "\n".join(result.summary_lines())
    assert f"{MINI_CANONICAL.datasource_id} / {MINI_CANONICAL.datasource_schema}" in plan
    assert f"{TARGET.datasource_id} / {TARGET.datasource_schema}" in plan


def test_the_predecessor_bug_is_caught(committed: CatalogDeclarativeWorkspaceModel) -> None:
    """The exact failure that shipped: a datasource id that is neither canonical nor target.

    The predecessor's `raw.replace('"globalmart-postgres"', ...)` was a no-op because the
    layout carried another id. Nothing raised, and a workspace shipped pointing at the wrong
    warehouse. Here the rewrite leaves a foreign id alone and the assertion names it.
    """
    for slot in iter_datasource_slots(committed):
        slot.set("some-other-org-datasource")

    with pytest.raises(UnresolvedLayoutError) as excinfo:
        resolve_and_assert(
            committed,
            canonical=MINI_CANONICAL,
            datasource_id=TARGET.datasource_id,
            datasource_schema=TARGET.datasource_schema,
        )

    message = str(excinfo.value)
    assert "some-other-org-datasource" in message
    assert TARGET.datasource_id in message


def test_a_foreign_table_schema_is_caught(committed: CatalogDeclarativeWorkspaceModel) -> None:
    next(iter(iter_table_schema_slots(committed))).set("someone_elses_schema")

    with pytest.raises(UnresolvedLayoutError) as excinfo:
        resolve_and_assert(
            committed,
            canonical=MINI_CANONICAL,
            datasource_id=TARGET.datasource_id,
            datasource_schema=TARGET.datasource_schema,
        )
    assert "someone_elses_schema" in str(excinfo.value)


def test_a_leftover_stage_a_placeholder_is_caught(committed: CatalogDeclarativeWorkspaceModel) -> None:
    """A tree still in the retired placeholder form must never reach an org."""
    for slot in iter_datasource_slots(committed):
        slot.set("{{ datasource_id }}")

    with pytest.raises(UnresolvedLayoutError) as excinfo:
        resolve_and_assert(
            committed,
            canonical=MINI_CANONICAL,
            datasource_id=TARGET.datasource_id,
            datasource_schema=TARGET.datasource_schema,
        )
    assert "unresolved placeholder" in str(excinfo.value)


def test_unresolved_token_in_an_unenumerated_field_is_caught(
    committed: CatalogDeclarativeWorkspaceModel,
) -> None:
    """The safety net: a placeholder somewhere no generator looks at."""
    committed.analytics.metrics[0].description = "See {{ some_future_token }} for details"

    rewrite_data_source(committed, source=MINI_CANONICAL, target=TARGET)

    with pytest.raises(UnresolvedLayoutError) as excinfo:
        assert_fully_resolved(committed, datasource_id=TARGET.datasource_id)
    assert "unresolved placeholder" in str(excinfo.value)


def test_audit_reports_without_raising(committed: CatalogDeclarativeWorkspaceModel) -> None:
    """A caller may want to report problems before deciding to fail."""
    unresolved, foreign = audit_resolution(
        committed, datasource_id=TARGET.datasource_id, datasource_schema=TARGET.datasource_schema
    )

    assert unresolved == []
    assert foreign[MINI_CANONICAL.datasource_id] == len(list(iter_datasource_slots(committed)))
    assert foreign[f"schema:{MINI_CANONICAL.datasource_schema}"] == len(
        list(iter_table_schema_slots(committed))
    )


def test_rewrite_is_idempotent(committed: CatalogDeclarativeWorkspaceModel) -> None:
    resolve_and_assert(
        committed,
        canonical=MINI_CANONICAL,
        datasource_id=TARGET.datasource_id,
        datasource_schema=TARGET.datasource_schema,
    )
    snapshot = blob(committed)

    rewrite_data_source(committed, source=MINI_CANONICAL, target=TARGET)

    assert blob(committed) == snapshot


def test_rewriting_there_and_back_is_the_identity(committed: CatalogDeclarativeWorkspaceModel) -> None:
    snapshot = blob(committed)

    rewrite_data_source(committed, source=MINI_CANONICAL, target=TARGET)
    rewrite_data_source(committed, source=TARGET, target=MINI_CANONICAL)

    assert blob(committed) == snapshot
