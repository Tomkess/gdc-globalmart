"""The synthetic generator: determinism, shape, keys and dates.

`test_referential_integrity_holds_across_every_table` is the one that matters. Integrity is
structural here — a foreign column draws from the target's minted key set rather than from a
generator that happens to use the same format — and this asserts that across all 215 tables
rather than a sample, because it is cheap and it is the property a later edit most easily
breaks.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
from datetime import date
from pathlib import Path

import pytest

from globalmart.dataload import verify_data
from globalmart.generate import (
    ColumnStrategy,
    GenerationError,
    base_row_counts,
    generate_dataset,
    plan_columns,
    row_count_for,
    table_seed,
)
from globalmart.registry import build_registry, foreign_key_target, own_key_column

REPO = Path(__file__).resolve().parents[1]
DDL = REPO / "data" / "ddl" / "globalmart.sql"
MANIFEST = REPO / "data" / "table-manifest.json"

pytestmark = pytest.mark.skipif(not DDL.exists(), reason="DDL not present")


@pytest.fixture(scope="module")
def registry():  # type: ignore[no-untyped-def]
    return build_registry(DDL)


@pytest.fixture(scope="module")
def counts():  # type: ignore[no-untyped-def]
    return base_row_counts(MANIFEST)


@pytest.fixture(scope="module")
def generated(tmp_path_factory, registry, counts):  # type: ignore[no-untyped-def]
    out = tmp_path_factory.mktemp("generated")
    generate_dataset(registry, out_dir=out, seed=7, scale=1.0, base_counts=counts)
    return out


def rows_of(out: Path, table: str) -> list[dict[str, str]]:
    with gzip.open(out / "tables" / f"{table}.csv.gz", "rb") as handle:
        return list(csv.DictReader(io.StringIO(handle.read().decode("utf-8"))))


def blob(out: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted((out / "tables").glob("*.csv.gz"))}


# --- resolution ---------------------------------------------------------------


def test_foreign_keys_resolve_to_their_table(registry) -> None:  # type: ignore[no-untyped-def]
    names = registry.names()

    assert foreign_key_target("customer_id", names) == "dim_customer"
    assert foreign_key_target("session_id", names) is None  # local id, not a reference
    assert foreign_key_target("not_an_id_column", names) is None


def test_own_keys_prefer_the_table_s_own_name(registry) -> None:  # type: ignore[no-untyped-def]
    assert own_key_column(registry.require("dim_customer")) == "customer_id"
    assert own_key_column(registry.require("fact_order_line")) == "order_line_id"


def test_every_table_plans_without_error(registry) -> None:  # type: ignore[no-untyped-def]
    """Registry-driven: a table added to the DDL must plan with no edit to the generator."""
    for name in registry.names():
        assert plan_columns(registry.require(name), registry.names())


def test_strategies_are_assigned_from_names_and_types(registry) -> None:  # type: ignore[no-untyped-def]
    plans = {p.column: p for p in plan_columns(registry.require("fact_order_header"), registry.names())}

    assert plans["order_id"].strategy is ColumnStrategy.OWN_KEY
    assert plans["customer_id"].strategy is ColumnStrategy.FOREIGN_KEY
    assert plans["customer_id"].target == "dim_customer"
    assert plans["order_date"].strategy is ColumnStrategy.DATE


# --- determinism --------------------------------------------------------------


def test_the_same_seed_produces_identical_bytes(tmp_path: Path, registry, counts) -> None:  # type: ignore[no-untyped-def]
    one, two = tmp_path / "a", tmp_path / "b"
    generate_dataset(registry, out_dir=one, seed=11, scale=1.0, base_counts=counts)
    generate_dataset(registry, out_dir=two, seed=11, scale=1.0, base_counts=counts)

    assert blob(one) == blob(two)
    assert (one / "table-manifest.json").read_bytes() == (two / "table-manifest.json").read_bytes()


def test_a_different_seed_produces_different_data(tmp_path: Path, registry, counts) -> None:  # type: ignore[no-untyped-def]
    """Guard: without this, a generator that ignored the seed would pass the test above."""
    one, two = tmp_path / "a", tmp_path / "b"
    generate_dataset(registry, out_dir=one, seed=11, scale=1.0, base_counts=counts)
    generate_dataset(registry, out_dir=two, seed=12, scale=1.0, base_counts=counts)

    assert blob(one) != blob(two)


def test_table_streams_are_independent() -> None:
    """One table's stream must not depend on another's, or a new table shifts everything."""
    assert table_seed(1, "dim_a") != table_seed(1, "dim_b")
    assert table_seed(1, "dim_a") == table_seed(1, "dim_a")
    assert table_seed(2, "dim_a") != table_seed(1, "dim_a")


# --- shape --------------------------------------------------------------------


def test_scale_one_reproduces_the_real_row_counts(generated, counts) -> None:  # type: ignore[no-untyped-def]
    """The archive is the shape reference, which is what makes the two comparable."""
    manifest = json.loads((generated / "table-manifest.json").read_text(encoding="utf-8"))
    produced = {table: entry["rows"] for table, entry in manifest["tables"].items()}

    assert produced == counts
    assert sum(produced.values()) == 174_372


def test_facts_scale_linearly_and_dimensions_by_sqrt(counts) -> None:  # type: ignore[no-untyped-def]
    assert row_count_for("fact_order_line", counts, 4.0) == counts["fact_order_line"] * 4
    assert row_count_for("dim_currency", counts, 4.0) == counts["dim_currency"] * 2


def test_a_dimension_never_shrinks(counts) -> None:  # type: ignore[no-untyped-def]
    """Shrinking reference data would drop keys the semantic layer's filters expect."""
    assert row_count_for("dim_currency", counts, 0.25) == counts["dim_currency"]
    assert row_count_for("fact_order_line", counts, 0.5) < counts["fact_order_line"]


def test_an_unknown_table_still_generates(counts) -> None:  # type: ignore[no-untyped-def]
    assert row_count_for("dim_brand_new", counts, 1.0) > 0


# --- the property that matters ------------------------------------------------


def test_referential_integrity_holds_across_every_table(generated, registry) -> None:  # type: ignore[no-untyped-def]
    """Every foreign value exists in the target's key set. All 215 tables, not a sample."""
    keys: dict[str, set[str]] = {}
    for name in registry.load_order:
        key_column = own_key_column(registry.require(name))
        if key_column:
            keys[name] = {row[key_column] for row in rows_of(generated, name)}

    checked = 0
    for name in registry.load_order:
        plans = [
            p
            for p in plan_columns(registry.require(name), registry.names())
            if p.strategy is ColumnStrategy.FOREIGN_KEY
        ]
        if not plans:
            continue
        data = rows_of(generated, name)
        for plan in plans:
            values = {row[plan.column] for row in data} - {""}
            assert values <= keys.get(plan.target or "", set()), f"{name}.{plan.column}"
            checked += 1

    assert checked > 100, "the assertion is only meaningful if it checked real columns"


def test_dates_fall_inside_the_configured_window(tmp_path: Path, registry, counts) -> None:  # type: ignore[no-untyped-def]
    """Existing visualizations filter on dates; values outside the window match nothing."""
    window = (date(2024, 1, 1), date(2024, 12, 31))
    generate_dataset(registry, out_dir=tmp_path, seed=7, scale=1.0, base_counts=counts, window=window)

    plans = plan_columns(registry.require("fact_order_header"), registry.names())
    date_columns = [p.column for p in plans if p.strategy is ColumnStrategy.DATE]
    assert date_columns

    for row in rows_of(tmp_path, "fact_order_header")[:200]:
        for column in date_columns:
            assert window[0] <= date.fromisoformat(row[column]) <= window[1]


# --- format and refusal -------------------------------------------------------


def test_the_output_is_what_feat005_s_loader_consumes(generated) -> None:  # type: ignore[no-untyped-def]
    """AC #6 without a warehouse: the loader's own verifier accepts the generated set."""
    result = verify_data(tables_dir=generated / "tables", manifest_path=generated / "table-manifest.json")

    assert result.ok()
    assert result.tables == 215


def test_the_manifest_records_what_produced_it(generated) -> None:  # type: ignore[no-untyped-def]
    manifest = json.loads((generated / "table-manifest.json").read_text(encoding="utf-8"))

    assert manifest["source"]["kind"] == "generated"
    assert manifest["source"]["seed"] == 7
    assert manifest["source"]["scale"] == 1.0


def test_generating_into_the_committed_archive_is_refused(registry, counts) -> None:  # type: ignore[no-untyped-def]
    """The archive is FEAT-005's. A variant must never silently become it."""
    with pytest.raises(GenerationError, match="committed archive"):
        generate_dataset(registry, out_dir=REPO / "data", seed=7, base_counts=counts)

    with pytest.raises(GenerationError, match="committed archive"):
        generate_dataset(registry, out_dir=REPO / "data" / "tables", seed=7, base_counts=counts)


def test_a_non_positive_scale_is_refused(tmp_path: Path, registry, counts) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(GenerationError, match="scale"):
        generate_dataset(registry, out_dir=tmp_path, seed=7, scale=0, base_counts=counts)


# --- no hardcoded schema knowledge --------------------------------------------


def test_the_generator_names_no_table_or_column(registry) -> None:  # type: ignore[no-untyped-def]
    """Every decision comes from the DDL and from name patterns, never from a list."""
    source = (REPO / "src" / "globalmart" / "generate.py").read_text(encoding="utf-8")

    for name in registry.names():
        assert name not in source, f"generate.py hardcodes the table {name}"

    sampled = ["customer_id", "order_date", "sales_amount", "store_name"]
    for column in sampled:
        assert column not in source, f"generate.py hardcodes the column {column}"


def test_the_declared_type_always_beats_the_column_name(registry) -> None:  # type: ignore[no-untyped-def]
    """`hour_start` is an INTEGER whose name ends in `_start`.

    Trusting the name over the type generated a date into an integer column and the
    warehouse rejected the load. Asserted across the whole DDL, not just that column,
    because the next name/type collision will be a different column.
    """
    for name in registry.names():
        table = registry.require(name)
        types = {column.name: column.sql_type.upper() for column in table.columns}
        for plan in plan_columns(table, registry.names()):
            declared = types[plan.column]
            if plan.strategy is ColumnStrategy.DATE:
                assert declared.startswith(("DATE", "TIMESTAMP", "VARCHAR")), (
                    f"{name}.{plan.column} is {declared} but plans as a date"
                )
            if declared.startswith("INT"):
                assert plan.strategy in (
                    ColumnStrategy.INTEGER,
                    ColumnStrategy.OWN_KEY,
                    ColumnStrategy.FOREIGN_KEY,
                ), f"{name}.{plan.column} is {declared} but plans as {plan.strategy}"


def test_generated_values_match_their_declared_type(tmp_path: Path, registry, counts) -> None:  # type: ignore[no-untyped-def]
    """The end of the same story: what is written must parse as what the DDL declares."""
    generate_dataset(registry, out_dir=tmp_path, seed=7, scale=0.01, base_counts=counts)

    for name in sorted(registry.names()):
        table = registry.require(name)
        types = {column.name: column.sql_type.upper() for column in table.columns}
        for row in rows_of(tmp_path, name)[:5]:
            for column, value in row.items():
                if not value:
                    continue
                declared = types[column]
                if declared.startswith("INT"):
                    int(value)  # raises if the generator wrote a date here
                elif declared.startswith("NUMERIC"):
                    float(value)
                elif declared.startswith("DATE"):
                    date.fromisoformat(value)


# --- workspace data filter columns (ADR 008 / FEAT-012) -----------------------


def test_every_table_carries_both_filter_columns(tmp_path: Path, registry, counts) -> None:  # type: ignore[no-untyped-def]
    """A filter layer that silently misses tables is the failure FEAT-011 already cost us."""
    from globalmart.generate import WDF_REGION_COLUMN, WDF_TENANT_COLUMN

    generate_dataset(registry, out_dir=tmp_path, seed=5, scale=0.02, base_counts=counts)

    for name in sorted(registry.names()):
        columns = rows_of(tmp_path, name)[0].keys()
        assert WDF_TENANT_COLUMN in columns, name
        assert WDF_REGION_COLUMN in columns, name


def test_filter_values_come_from_the_declared_vocabulary(tmp_path: Path, registry, counts) -> None:  # type: ignore[no-untyped-def]
    from globalmart.generate import WDF_VOCABULARY

    generate_dataset(registry, out_dir=tmp_path, seed=5, scale=0.02, base_counts=counts)

    for name in sorted(registry.names()):
        for row in rows_of(tmp_path, name)[:5]:
            for column, vocabulary in WDF_VOCABULARY.items():
                assert row[column] in vocabulary, f"{name}.{column} = {row[column]!r}"


def test_a_fact_agrees_with_the_entity_it_references(tmp_path: Path, registry, counts) -> None:  # type: ignore[no-untyped-def]
    """Coherence is the whole point: a tenant filter must not return half a store."""
    from globalmart.generate import WDF_REGION_COLUMN, WDF_TENANT_COLUMN

    generate_dataset(registry, out_dir=tmp_path, seed=5, scale=0.2, base_counts=counts)

    stores = {
        row["store_id"]: (row[WDF_TENANT_COLUMN], row[WDF_REGION_COLUMN])
        for row in rows_of(tmp_path, "dim_store")
    }
    assert stores, "dim_store minted no keys, so this proves nothing"

    linked = 0
    for row in rows_of(tmp_path, "fact_daily_store_sales"):
        if row["store_id"] not in stores:
            continue
        linked += 1
        assert (row[WDF_TENANT_COLUMN], row[WDF_REGION_COLUMN]) == stores[row["store_id"]]

    assert linked > 0, "no fact row referenced a real store, so nothing was checked"


def test_a_table_without_its_own_identity_does_not_hijack_a_foreign_key() -> None:
    """`fact_daily_store_sales` has no identity of its own — its grain is a date and a store.

    Taking its first `_id` made it mint `store_id` values, so the table joined to nothing.
    Nine tables were affected, including inventory and product performance.
    """
    from globalmart.registry import own_key_column

    registry = build_registry(DDL)
    known = frozenset(registry.names())

    assert own_key_column(registry.require("fact_daily_store_sales"), known) is None
    assert own_key_column(registry.require("dim_store"), known) == "store_id"
