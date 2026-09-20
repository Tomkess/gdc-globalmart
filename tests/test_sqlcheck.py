"""Do the SQL-backed datasets resolve against the schema the DDL describes?

The headline case: `sql_channel_attribution` selects `FROM {{ datasource_schema }}.fact_search_event`,
a table that had no DDL and no CSV. The dataset was broken from the day it was written and
nothing noticed, because a layout publishes fine whether or not its SQL can run. This module
is the check that would have caught it — offline, no warehouse, no credentials.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from globalmart.layout_io import read_tree
from globalmart.registry import Table, build_registry
from globalmart.sqlcheck import (
    SqlCheckError,
    check_sql_datasets,
    raise_for_sql_report,
    referenced_tables,
)

REPO = Path(__file__).resolve().parents[1]
DDL = REPO / "data" / "ddl" / "globalmart.sql"
LAYOUT = REPO / "layouts" / "workspaces" / "globalmart"

pytestmark = pytest.mark.skipif(
    not (DDL.exists() and LAYOUT.exists()), reason="DDL or layout not present"
)


@pytest.fixture(scope="module")
def model():  # type: ignore[no-untyped-def]
    return read_tree(LAYOUT)


@pytest.fixture(scope="module")
def registry(model):  # type: ignore[no-untyped-def]
    return build_registry(DDL, model=model)


def test_reference_extraction() -> None:
    statement = (
        "SELECT * FROM {{ datasource_schema }}.fact_a a "
        "JOIN {{ datasource_schema }}.dim_b b ON a.id = b.id "
        "JOIN {{ datasource_schema }}.dim_b b2 ON a.id2 = b2.id"
    )
    assert referenced_tables(statement, "globalmart") == ("dim_b", "fact_a")


def test_a_reference_to_another_schema_is_ignored() -> None:
    """Only tables in the target schema are this repo's to account for."""
    statement = "SELECT * FROM {{ datasource_schema }}.fact_a JOIN other.thing t ON 1=1"
    assert referenced_tables(statement, "globalmart") == ("fact_a",)


def test_all_eleven_sql_datasets_resolve(model, registry) -> None:  # type: ignore[no-untyped-def]
    report = check_sql_datasets(model, registry, schema="globalmart")

    assert len(report.checks) == 11
    assert report.ok(), [c.dataset_id for c in report.failures()]
    raise_for_sql_report(report)


def test_channel_attribution_needs_the_table_that_did_not_exist(model, registry) -> None:  # type: ignore[no-untyped-def]
    """The specific dataset, named, so the regression is unmistakable."""
    report = check_sql_datasets(model, registry, schema="globalmart")
    check = next(c for c in report.checks if c.dataset_id == "sql_channel_attribution")

    assert "fact_search_event" in check.tables
    assert check.missing_tables == ()


def test_without_fact_search_event_the_check_fails(model, registry) -> None:  # type: ignore[no-untyped-def]
    """What the repo looked like before this feature: the check must catch it.

    Without this negative case, `test_all_eleven_sql_datasets_resolve` passing would not
    prove the check works — only that nothing is currently broken.
    """
    crippled = Table(name="unused", columns=())
    trimmed = {k: v for k, v in registry.tables.items() if k != "fact_search_event"}
    trimmed.setdefault("unused", crippled)
    narrowed = type(registry)(tables=trimmed, load_order=tuple(sorted(trimmed)))

    report = check_sql_datasets(model, narrowed, schema="globalmart")

    assert not report.ok()
    failures = {c.dataset_id for c in report.failures()}
    assert "sql_channel_attribution" in failures

    with pytest.raises(SqlCheckError, match="fact_search_event"):
        raise_for_sql_report(report)


def test_the_check_is_offline(model, registry) -> None:
    """No loader supplied means nothing is executed — this runs in CI without credentials."""
    report = check_sql_datasets(model, registry, schema="globalmart")

    assert all(check.executed is False for check in report.checks)


def test_live_execution_is_reported_when_a_loader_is_supplied(model, registry) -> None:  # type: ignore[no-untyped-def]
    class Executor:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def execute(self, statement: str) -> None:
            self.statements.append(statement)

    executor = Executor()
    report = check_sql_datasets(model, registry, schema="globalmart", loader=executor)

    assert all(check.executed for check in report.checks)
    assert len(executor.statements) == 11
    # LIMIT 0: the planner resolves columns without moving rows.
    assert all(s.endswith("LIMIT 0") for s in executor.statements)
    assert all("{{ datasource_schema }}" not in s for s in executor.statements)


def test_a_failing_statement_is_reported_not_raised(model, registry) -> None:  # type: ignore[no-untyped-def]
    class Broken:
        def execute(self, statement: str) -> None:
            raise RuntimeError("Binder Error: column does not exist")

    report = check_sql_datasets(model, registry, schema="globalmart", loader=Broken())

    assert not report.ok()
    assert len(report.failures()) == 11
    with pytest.raises(SqlCheckError, match="Binder Error"):
        raise_for_sql_report(report)
