"""FEAT-021 — realistic, coherent labels.

Every rendered text attribute was a placeholder (`City Name 0005`), and the geography under it
was incoherent: a row's references were drawn independently, so 54 of 100 cities sat in a
different country from their own region. These tests hold the generator to coherent references
and to the vocabulary in `config/vocabulary.yaml`.
"""

from __future__ import annotations

import csv
import gzip
import io
import re
from pathlib import Path

import pytest

from globalmart.generate import ColumnStrategy, base_row_counts, generate_dataset, plan_columns
from globalmart.layout_io import read_tree
from globalmart.registry import build_registry
from globalmart.vocabulary import (
    DEFAULT_VOCABULARY_PATH,
    VocabularyError,
    composed,
    load_vocabulary,
)

REPO = Path(__file__).resolve().parents[1]
DDL = REPO / "data" / "ddl" / "globalmart.sql"
LAYOUT = REPO / "gd_data_product" / "globalmart"
MANIFEST = REPO / "data" / "table-manifest.json"
VOCABULARY = REPO / DEFAULT_VOCABULARY_PATH

#: The 12 text columns a GlobalMart visualization renders (measured 2026-10-23).
RENDERED = {
    "dim_channel_master": ("channel_type", "channel_name"),
    "dim_company_entity": ("entity_name",),
    "dim_currency": ("currency_code", "currency_name"),
    "dim_customer": ("customer_name",),
    "dim_geography_city": ("city_name",),
    "dim_geography_country": ("country_name",),
    "dim_geography_region": ("region_name",),
    "dim_product": ("product_name",),
    "dim_store": ("store_format", "store_name"),
}
PLACEHOLDER = re.compile(r"(Name \d{4}$)|(_\d{5}$)")

pytestmark = pytest.mark.skipif(not (DDL.exists() and LAYOUT.exists()), reason="artifacts not present")


# --- the loader ---------------------------------------------------------------


def test_a_missing_file_means_no_vocabulary(tmp_path: Path) -> None:
    assert load_vocabulary(tmp_path / "absent.yaml") is None


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("version: 2\n", "version: 1"),
        ("version: 1\ntables:\n  t:\n    colours: {}\n", "unknown key"),
        ("version: 1\ntables:\n  t:\n    by_parent:\n      - {column: c, via: v}\n", "lacks"),
        ("version: 1\ntables:\n  t:\n    compose:\n      c: [[a, b]]\n", "two or more"),
    ],
)
def test_malformed_vocabularies_are_refused(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "vocabulary.yaml"
    path.write_text(text)
    with pytest.raises(VocabularyError, match=message):
        load_vocabulary(path)


def test_composition_never_repeats_before_it_runs_out() -> None:
    lists = (("a", "b", "c"), ("x", "y"), ("1", "2", "3", "4"))
    names = [composed(lists, i) for i in range(24)]
    assert len(set(names)) == 24


def test_the_committed_vocabulary_covers_every_rendered_column() -> None:
    vocabulary = load_vocabulary(VOCABULARY)
    assert vocabulary is not None
    for table, columns in RENDERED.items():
        written = vocabulary.for_table(table)
        assert written is not None, table
        assert set(columns) <= written.columns(), (table, set(columns) - written.columns())


# --- generated data -----------------------------------------------------------


@pytest.fixture(scope="module")
def registry():  # type: ignore[no-untyped-def]
    return build_registry(DDL, model=read_tree(LAYOUT))


@pytest.fixture(scope="module")
def generated(tmp_path_factory, registry):  # type: ignore[no-untyped-def]
    out = tmp_path_factory.mktemp("vocab")
    generate_dataset(
        registry,
        out_dir=out,
        seed=7,
        scale=0.05,
        base_counts=base_row_counts(MANIFEST),
        vocabulary=load_vocabulary(VOCABULARY),
    )
    return out


def _rows(out: Path, table: str) -> list[dict[str, str]]:
    with gzip.open(out / "tables" / f"{table}.csv.gz", "rb") as handle:
        return list(csv.DictReader(io.StringIO(handle.read().decode("utf-8"))))


def test_no_rendered_column_is_a_placeholder(generated) -> None:  # type: ignore[no-untyped-def]
    for table, columns in RENDERED.items():
        for row in _rows(generated, table):
            for column in columns:
                assert row[column] and not PLACEHOLDER.search(row[column]), (table, column, row[column])


def test_every_reference_agrees_with_the_row_it_points_at(generated, registry) -> None:  # type: ignore[no-untyped-def]
    """Transitive coherence across every pair the LDM implies, in every table, not a sample."""
    keys = {}
    for name in registry.names():
        plans = plan_columns(registry.require(name), registry.names(), registry.references_of(name))
        own = next((p.column for p in plans if p.strategy is ColumnStrategy.OWN_KEY), None)
        if own:
            keys[name] = {row[own]: row for row in _rows(generated, name)}

    violations = []
    for name in sorted(registry.names()):
        refs = registry.references_of(name)
        if len(refs) < 2:
            continue
        rows = _rows(generated, name)
        for a, a_target in refs.items():
            for via, via_target in registry.references_of(a_target).items():
                derived = next((c for c, t in refs.items() if t == via_target and c != a), None)
                if derived is None or a_target not in keys:
                    continue
                for row in rows:
                    parent = keys[a_target].get(row[a])
                    if parent and parent[via] and row[derived] != parent[via]:
                        violations.append(f"{name}.{derived} disagrees with {a_target}.{via}")
                        break
    assert violations == []


def test_names_live_inside_their_parent(generated) -> None:  # type: ignore[no-untyped-def]
    vocabulary = load_vocabulary(VOCABULARY)
    assert vocabulary is not None
    countries = {r["country_id"]: r["country_name"] for r in _rows(generated, "dim_geography_country")}
    regions = {r["region_id"]: r for r in _rows(generated, "dim_geography_region")}
    region_rule = vocabulary.for_table("dim_geography_region").by_parent[0]  # type: ignore[union-attr]
    city_rule = vocabulary.for_table("dim_geography_city").by_parent[0]  # type: ignore[union-attr]

    for region in regions.values():
        base = re.sub(r" \d+$", "", region["region_name"])
        assert base in region_rule.values[countries[region["country_id"]]]
    for city in _rows(generated, "dim_geography_city"):
        base = re.sub(r" \d+$", "", city["city_name"])
        assert base in city_rule.values[regions[city["region_id"]]["region_name"]]


def test_paired_columns_agree_and_countries_pay_in_their_currency(generated) -> None:  # type: ignore[no-untyped-def]
    currencies = {r["currency_id"]: r for r in _rows(generated, "dim_currency")}
    by_code = {r["currency_code"]: r for r in currencies.values()}
    assert (
        by_code["USD"]["currency_name"] == "US Dollar" and by_code["USD"]["exchange_rate_to_usd"] == "1.0000"
    )
    paid = {
        r["country_name"]: currencies[r["currency_id"]]["currency_code"]
        for r in _rows(generated, "dim_geography_country")
    }
    assert paid == {"United States": "USD", "Canada": "CAD"}


def test_the_us_carries_most_of_the_business(generated) -> None:  # type: ignore[no-untyped-def]
    """Left to chance, 5 of 8 regions fell in Canada and ~70% of orders with them."""
    countries = {r["country_id"]: r["country_name"] for r in _rows(generated, "dim_geography_country")}
    for table in ("dim_geography_region", "dim_store", "dim_customer"):
        rows = _rows(generated, table)
        us = sum(countries[r["country_id"]] == "United States" for r in rows)
        assert us / len(rows) >= 0.6, (table, us, len(rows))


def test_dimension_names_are_distinct(generated) -> None:  # type: ignore[no-untyped-def]
    for table, column in [
        ("dim_customer", "customer_name"),
        ("dim_product", "product_name"),
        ("dim_store", "store_name"),
        ("dim_geography_city", "city_name"),
    ]:
        names = [row[column] for row in _rows(generated, table)]
        assert len(names) == len(set(names)), table


def test_generation_with_a_vocabulary_is_deterministic(tmp_path: Path, registry) -> None:  # type: ignore[no-untyped-def]
    vocabulary = load_vocabulary(VOCABULARY)
    counts = base_row_counts(MANIFEST)
    for run in ("a", "b"):
        generate_dataset(
            registry, out_dir=tmp_path / run, seed=11, scale=0.02, base_counts=counts, vocabulary=vocabulary
        )
    a = {p.name: p.read_bytes() for p in (tmp_path / "a" / "tables").glob("*.csv.gz")}
    b = {p.name: p.read_bytes() for p in (tmp_path / "b" / "tables").glob("*.csv.gz")}
    assert a == b
