"""FEAT-020 — generated data honours the LDM's foreign keys.

The generator chose a foreign key's target table by guessing from the column name
(`channel_id` -> `dim_channel`). Where no such table existed, it filled the column with values
that matched nothing. On 2026-10-23 that was 36 of the 184 references between tables, so every
breakdown by channel, country, city or company entity joined to nothing. The LDM states every
relationship, so it now decides, and these tests hold it to that across the whole layout.
"""

from __future__ import annotations

import csv
import gzip
import io
from pathlib import Path

import pytest

from globalmart.generate import ColumnStrategy, base_row_counts, generate_dataset, plan_columns
from globalmart.layout_io import read_tree
from globalmart.registry import build_registry

REPO = Path(__file__).resolve().parents[1]
DDL = REPO / "data" / "ddl" / "globalmart.sql"
LAYOUT = REPO / "gd_data_product" / "globalmart"
MANIFEST = REPO / "data" / "table-manifest.json"

pytestmark = pytest.mark.skipif(not (DDL.exists() and LAYOUT.exists()), reason="artifacts not present")


@pytest.fixture(scope="module")
def model():  # type: ignore[no-untyped-def]
    return read_tree(LAYOUT)


@pytest.fixture(scope="module")
def registry(model):  # type: ignore[no-untyped-def]
    return build_registry(DDL, model=model)


def _ldm_table_references(model, tables) -> list[tuple[str, str, str]]:  # type: ignore[no-untyped-def]
    """`(table, column, referenced table)` for every LDM reference between two tables."""
    found = []
    for dataset in model.ldm.datasets:
        if dataset.id not in tables:
            continue
        for reference in dataset.references or []:
            target = reference.identifier.id
            if target in tables and target != dataset.id:
                found.extend((dataset.id, source.column, target) for source in reference.sources)
    return found


def test_every_ldm_reference_plans_to_the_table_it_names(registry, model) -> None:  # type: ignore[no-untyped-def]
    references = _ldm_table_references(model, registry.names())
    assert len(references) >= 174, "the layout lost references — the audit no longer means much"

    wrong = []
    for table, column, target in references:
        plans = {
            p.column: p
            for p in plan_columns(registry.require(table), registry.names(), registry.references_of(table))
        }
        plan = plans[column]
        if plan.strategy is not ColumnStrategy.FOREIGN_KEY or plan.target != target:
            wrong.append(f"{table}.{column}: LDM -> {target}, planned {plan.strategy} -> {plan.target}")
    assert wrong == []


def test_the_case_that_surfaced_it(registry) -> None:  # type: ignore[no-untyped-def]
    plans = {
        p.column: p
        for p in plan_columns(
            registry.require("fact_order_header"),
            registry.names(),
            registry.references_of("fact_order_header"),
        )
    }
    assert plans["channel_id"].strategy is ColumnStrategy.FOREIGN_KEY
    assert plans["channel_id"].target == "dim_channel_master"


def test_without_a_model_naming_inference_is_unchanged() -> None:
    """`data generate` without a layout keeps the old behaviour; nothing is invented."""
    bare = build_registry(DDL)
    assert bare.foreign_keys == {}
    plans = {p.column: p for p in plan_columns(bare.require("fact_order_header"), bare.names())}
    assert plans["customer_id"].target == "dim_customer"  # naming still resolves this one
    assert plans["channel_id"].strategy is ColumnStrategy.CODE  # and still cannot resolve this one


def _rows(out: Path, table: str) -> list[dict[str, str]]:
    with gzip.open(out / "tables" / f"{table}.csv.gz", "rb") as handle:
        return list(csv.DictReader(io.StringIO(handle.read().decode("utf-8"))))


def test_generated_rows_never_point_at_a_key_that_does_not_exist(tmp_path: Path, registry, model) -> None:  # type: ignore[no-untyped-def]
    """The acceptance criterion as data: 0 of the references dangle in what is actually written."""
    report = generate_dataset(
        registry, out_dir=tmp_path, seed=7, scale=0.02, base_counts=base_row_counts(MANIFEST)
    )
    assert report.unresolved == {}

    keys: dict[str, set[str]] = {}
    dangling = []
    for table, column, target in _ldm_table_references(model, registry.names()):
        if target not in keys:
            key_plan = next(
                p
                for p in plan_columns(
                    registry.require(target), registry.names(), registry.references_of(target)
                )
                if p.strategy is ColumnStrategy.OWN_KEY
            )
            keys[target] = {row[key_plan.column] for row in _rows(tmp_path, target)}
        values = {row[column] for row in _rows(tmp_path, table) if row[column]}
        missing = values - keys[target]
        if missing:
            dangling.append(
                f"{table}.{column} -> {target}: {len(missing)} of {len(values)} values match nothing"
            )
    assert dangling == []
