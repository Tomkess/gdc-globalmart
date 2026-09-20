"""The table registry, derived from the DDL rather than hardcoded beside it.

The predecessor kept a 214-entry `LOAD_ORDER` list next to the DDL. Two sources for one
fact, and adding a table meant editing both — so the interesting assertions here are that
the registry matches the DDL exactly and that nothing else in the repo carries a table list.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from globalmart.registry import RegistryError, build_registry, parse_ddl, render_ddl

REPO = Path(__file__).resolve().parents[1]
DDL = REPO / "data" / "ddl" / "globalmart.sql"

pytestmark = pytest.mark.skipif(not DDL.exists(), reason="DDL not committed yet")


def test_every_table_is_parsed() -> None:
    tables = parse_ddl(DDL)

    assert len(tables) == 215
    assert "dim_store" in tables
    assert "fact_order_line" in tables


def test_columns_are_parsed_in_order() -> None:
    tables = parse_ddl(DDL)

    assert tables["dim_store"].column_names() == (
        "store_id",
        "store_name",
        "region_id",
        "city_id",
        "country_id",
        "store_format",
        "sqft",
    )


def test_the_215th_table_exists() -> None:
    """`sql_channel_attribution` selects from it; no DDL for it existed before FEAT-005."""
    tables = parse_ddl(DDL)

    assert tables["fact_search_event"].column_names() == (
        "session_id",
        "customer_id",
        "traffic_source",
        "session_date",
    )


def test_load_order_covers_every_table_exactly_once() -> None:
    registry = build_registry(DDL)

    assert len(registry.load_order) == len(registry.tables)
    assert set(registry.load_order) == registry.names()


def test_truncate_order_is_the_reverse() -> None:
    registry = build_registry(DDL)
    assert registry.truncate_order() == tuple(reversed(registry.load_order))


def test_load_order_is_deterministic_without_a_model() -> None:
    assert build_registry(DDL).load_order == build_registry(DDL).load_order


def test_the_join_graph_puts_dimensions_before_their_dependants() -> None:
    """Ordering is derived from the LDM, since the DDL declares no constraints at all."""
    from globalmart.layout_io import read_tree

    layout = REPO / "layouts" / "workspaces" / "globalmart"
    if not layout.exists():
        pytest.skip("real layout tree not present")

    registry = build_registry(DDL, model=read_tree(layout))
    order = list(registry.load_order)

    assert order.index("dim_geography_country") < order.index("dim_customer")
    assert order.index("dim_customer") < order.index("fact_order_header")


def test_the_ddl_declares_no_constraints() -> None:
    """Pinned as a fact, because it is why the load is truncate-then-load, not upsert.

    With no PRIMARY KEY anywhere there is no merge key, so there is nothing to upsert on.
    If constraints are ever added this test fails and the loading strategy gets revisited
    deliberately rather than by accident.
    """
    text = DDL.read_text(encoding="utf-8").upper()

    assert "PRIMARY KEY" not in text
    assert "FOREIGN KEY" not in text


def test_render_substitutes_the_schema() -> None:
    rendered = render_ddl(DDL, "somewhere_else")

    assert "{schema_name}" not in rendered
    assert "somewhere_else.dim_store" in rendered


def test_a_missing_ddl_is_named(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="No DDL"):
        parse_ddl(tmp_path / "nope.sql")


def test_a_ddl_with_no_tables_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "empty.sql"
    path.write_text("-- nothing here\n", encoding="utf-8")

    with pytest.raises(RegistryError, match="no CREATE TABLE"):
        parse_ddl(path)
