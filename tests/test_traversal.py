"""Task 3 — the shared enumeration both normalize and resolve depend on."""

from __future__ import annotations

from pathlib import Path

from globalmart.layout_io import read_tree
from globalmart.traversal import (
    iter_all_string_fields,
    iter_datasource_slots,
    iter_sql_statements,
)

FIXTURE = Path(__file__).parent / "fixtures" / "mini_globalmart"


def test_one_slot_per_dataset_on_the_fixture() -> None:
    """No GlobalMart dataset carries both a table id and SQL, so slots == datasets."""
    model = read_tree(FIXTURE)
    slots = list(iter_datasource_slots(model))

    assert len(slots) == len(model.ldm.datasets)


def test_slots_cover_both_table_and_sql_shapes() -> None:
    model = read_tree(FIXTURE)
    paths = [slot.path for slot in iter_datasource_slots(model)]

    assert any(p.endswith("dataSourceTableId.dataSourceId") for p in paths)
    assert any(p.endswith("sql.dataSourceId") for p in paths)


def test_slot_set_actually_mutates_the_model() -> None:
    """A slot that reads but does not write would make resolution a silent no-op."""
    model = read_tree(FIXTURE)
    for slot in iter_datasource_slots(model):
        slot.set("probe-value")

    assert all(slot.get() == "probe-value" for slot in iter_datasource_slots(model))


def test_slot_paths_name_their_dataset() -> None:
    """Error messages must point at the offending object, not just say 'somewhere'."""
    model = read_tree(FIXTURE)
    dataset_ids = {d.id for d in model.ldm.datasets}

    for slot in iter_datasource_slots(model):
        assert any(f"[{ds}]" in slot.path for ds in dataset_ids)


def test_sql_statement_slots_are_writable() -> None:
    model = read_tree(FIXTURE)
    statements = list(iter_sql_statements(model))
    assert statements, "fixture must carry a SQL dataset"

    for slot in statements:
        slot.set("SELECT 1")
    assert all(slot.get() == "SELECT 1" for slot in iter_sql_statements(model))


def test_all_string_fields_reaches_nested_content() -> None:
    """The safety net must see into untyped content blobs, not just modelled fields."""
    model = read_tree(FIXTURE)
    model.analytics.metrics[0].description = "sentinel-value-xyz"

    values = {value for _, value in iter_all_string_fields(model)}
    assert "sentinel-value-xyz" in values


def test_all_string_fields_yields_usable_paths() -> None:
    model = read_tree(FIXTURE)
    paths = [path for path, _ in iter_all_string_fields(model)]

    assert any(path.startswith("ldm.") for path in paths)
    assert any(path.startswith("analytics.") for path in paths)


# --- FEAT-003 task 9: dashboard -> visualization references -------------------


def test_dashboard_insight_refs_finds_the_known_pairs() -> None:
    from globalmart.traversal import iter_dashboard_insight_refs

    pairs = set(iter_dashboard_insight_refs(read_tree(FIXTURE)))

    assert ("dashboard_000", "viz_sales_0000") in pairs
    assert ("dashboard_mixed", "viz_sales_0000") in pairs


def test_dashboard_insight_refs_sees_into_a_nested_layout() -> None:
    """The reason the walk is generic: a shape-assuming extractor silently under-counts."""
    from globalmart.traversal import dashboard_visualization_ids

    found = dashboard_visualization_ids(read_tree(FIXTURE), "dashboard_mixed")

    # Nested two layouts deep, not at sections[].items[].widget.insight.
    assert "viz_sales_0000" in found


def test_dashboard_insight_refs_sees_a_drill_target() -> None:
    from globalmart.traversal import dashboard_visualization_ids

    found = dashboard_visualization_ids(read_tree(FIXTURE), "dashboard_mixed")

    # Reachable only through drills[].target.identifier.
    assert "viz_finance_0216" in found


def test_a_dashboard_with_no_references_yields_nothing() -> None:
    from globalmart.traversal import dashboard_visualization_ids

    model = read_tree(FIXTURE)
    model.analytics.analytical_dashboards[0].content = {}

    assert dashboard_visualization_ids(model, model.analytics.analytical_dashboards[0].id) == set()
