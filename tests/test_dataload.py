"""Data integrity, the ADR 004 guards, and the two defects this feature exists to fix.

Everything offline, against a `FakeLoader` that behaves like a warehouse: it holds row
counts, it can be truncated, and it appends on load. That last detail matters — the fake
*appends*, exactly like the predecessor's plain `INSERT`, so a loader that forgot to
truncate would double here too and `test_loading_twice_does_not_double` would catch it.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from globalmart.config import TargetProfile, WarehouseType
from globalmart.dataload import (
    DataIntegrityError,
    DataOwnershipError,
    load_data,
    verify_contract,
)
from globalmart.registry import build_registry

REPO = Path(__file__).resolve().parents[1]
DDL = REPO / "data" / "ddl" / "globalmart.sql"
TABLES = REPO / "data" / "tables"
MANIFEST = REPO / "data" / "table-manifest.json"


class FakeLoader:
    """A warehouse that appends, so a missing truncate is visible as doubling."""

    warehouse = "fake"

    def __init__(
        self,
        *,
        existing: set[str] | None = None,
        latest: str | None = None,
        live_columns: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.rows: dict[str, int] = dict.fromkeys(existing or set(), 0)
        self.calls: list[str] = []
        self.ddl_applied = False
        self.latest = latest
        self.live_columns: dict[str, tuple[str, ...]] = live_columns or {}

    def connect(self) -> None:
        self.calls.append("connect")

    def close(self) -> None:
        self.calls.append("close")

    def apply_ddl(self, ddl: str) -> None:
        self.ddl_applied = True
        self.calls.append("apply_ddl")

    def existing_tables(self, schema: str) -> set[str]:
        return set(self.rows)

    def row_count(self, schema: str, table: str) -> int:
        return self.rows.get(table, 0)

    def max_value(self, schema: str, table: str, column: str) -> str | None:
        return self.latest

    def columns(self, schema: str, table: str) -> tuple[str, ...]:
        """What the warehouse has. Defaults to whatever the DDL declares, so a test only
        has to say so when it wants drift."""
        return self.live_columns.get(table, ())

    def truncate(self, schema: str, table: str) -> None:
        self.calls.append(f"truncate:{table}")
        self.rows[table] = 0

    def load_csv(self, schema: str, table: str, csv_path: Path, columns: tuple[str, ...]) -> int:
        with csv_path.open(encoding="utf-8") as handle:
            inserted = max(sum(1 for _ in handle) - 1, 0)
        self.rows[table] = self.rows.get(table, 0) + inserted  # appends, deliberately
        return self.rows[table]


def profile(**overrides: Any) -> TargetProfile:
    base = TargetProfile(
        name="fake",
        host="https://example.invalid",
        token="t",
        organization_id="org",
        datasource_id="ds",
        datasource_schema="globalmart",
        warehouse_type=WarehouseType.MOTHERDUCK,
        datasource_secret_env="MOTHERDUCK_TOKEN",
        warehouse_database="db",
        data_owned=True,
    )
    return replace(base, **overrides)


pytestmark = pytest.mark.skipif(not MANIFEST.exists(), reason="contract not present")


@pytest.fixture(scope="session")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A generated dataset, standing where the committed archive used to.

    ADR 008 removed the rows from the repository, so the load tests generate what they load.
    That is a better test than the archive was: it exercises generation and loading together,
    which is exactly the path a rebuild takes.
    """
    from globalmart.generate import generate_dataset

    out = tmp_path_factory.mktemp("dataset")
    registry = build_registry(DDL)
    generate_dataset(registry, out_dir=out, seed=1, scale=0.05)
    return out


@pytest.fixture(scope="module")
def registry():  # type: ignore[no-untyped-def]
    return build_registry(DDL)


# --- the committed contract ---------------------------------------------------
#
# ADR 008 moved the rows out of the repository, so these no longer hash bytes. What is
# committed is the contract, and what it must satisfy is agreement with the DDL. Byte
# integrity still matters for a *generated* dataset and is checked by `verify_data` at load
# time, which the tests further down exercise against temporary directories.


def test_the_contract_covers_every_declared_table(registry) -> None:  # type: ignore[no-untyped-def]
    result = verify_contract(registry, manifest_path=MANIFEST)

    assert result.ok(), result.summary_lines()
    assert result.tables == 215
    assert result.rows == 174_372


def test_a_table_missing_from_the_contract_is_reported(tmp_path: Path, registry) -> None:  # type: ignore[no-untyped-def]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    del manifest["tables"]["dim_store"]
    path = tmp_path / "table-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    result = verify_contract(registry, manifest_path=path)

    assert not result.ok()
    assert "dim_store" in result.missing_from_contract


def test_a_column_that_drifts_from_the_ddl_is_reported(tmp_path: Path, registry) -> None:  # type: ignore[no-untyped-def]
    """A contract whose columns drifted would load values into the wrong columns."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["tables"]["dim_store"]["columns"] = ["store_id"]
    path = tmp_path / "table-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    result = verify_contract(registry, manifest_path=path)

    assert not result.ok()
    assert "dim_store" in result.column_drift


def test_the_rows_are_no_longer_committed() -> None:
    """ADR 008, asserted rather than assumed: the archive is gone and stays gone."""
    assert not (REPO / "data" / "tables").exists()


# --- the ADR 004 guards -------------------------------------------------------


def test_a_load_is_refused_without_data_owned(registry, dataset) -> None:  # type: ignore[no-untyped-def]
    loader = FakeLoader()

    with pytest.raises(DataOwnershipError, match="data_owned"):
        load_data(
            profile(data_owned=False),
            apply=True,
            loader=loader,
            registry=registry,
            tables_dir=dataset / "tables",
            manifest_path=dataset / "table-manifest.json",
            ddl_path=DDL,
        )
    assert loader.calls == []


def test_a_rehearsal_is_allowed_without_data_owned(registry, dataset) -> None:  # type: ignore[no-untyped-def]
    """Reading is always safe; it is truncating that needs permission."""
    loader = FakeLoader()
    report = load_data(
        profile(data_owned=False),
        loader=loader,
        registry=registry,
        tables_dir=dataset / "tables",
        manifest_path=dataset / "table-manifest.json",
        ddl_path=DDL,
    )

    assert report.applied is False
    assert not any(call.startswith("truncate") for call in loader.calls)


def test_an_unknown_table_in_the_schema_refuses_the_whole_load(registry, dataset) -> None:  # type: ignore[no-untyped-def]
    """A mistyped schema must not cost someone else their data."""
    loader = FakeLoader(existing={"dim_store", "somebody_elses_table"})

    with pytest.raises(DataOwnershipError, match="somebody_elses_table"):
        load_data(
            profile(),
            apply=True,
            loader=loader,
            registry=registry,
            tables_dir=dataset / "tables",
            manifest_path=dataset / "table-manifest.json",
            ddl_path=DDL,
        )
    assert not any(call.startswith("truncate") for call in loader.calls)


def test_the_census_is_taken_before_anything_is_truncated(registry, dataset) -> None:  # type: ignore[no-untyped-def]
    loader = FakeLoader(existing=set(registry.names()))
    loader.rows["dim_store"] = 42

    report = load_data(
        profile(),
        apply=True,
        loader=loader,
        registry=registry,
        tables_dir=dataset / "tables",
        manifest_path=dataset / "table-manifest.json",
        ddl_path=DDL,
        only={"dim_store"},
    )

    assert report.census["dim_store"] == 42
    assert report.tables[0].rows_before == 42


def test_the_census_is_taken_in_a_rehearsal_too(registry, dataset) -> None:  # type: ignore[no-untyped-def]
    loader = FakeLoader(existing=set(registry.names()))
    loader.rows["dim_store"] = 7

    report = load_data(
        profile(),
        loader=loader,
        registry=registry,
        tables_dir=dataset / "tables",
        manifest_path=dataset / "table-manifest.json",
        ddl_path=DDL,
        only={"dim_store"},
    )

    assert report.census["dim_store"] == 7
    assert report.rows_overwritten() == 7


# --- the two defects ----------------------------------------------------------


def test_loading_twice_does_not_double(registry, dataset) -> None:  # type: ignore[no-untyped-def]
    """The predecessor's defect. The fake appends, so a missing truncate doubles here too."""
    loader = FakeLoader(existing=set(registry.names()))
    only = {"dim_store", "dim_product", "fact_search_event"}
    kwargs: dict[str, Any] = dict(
        loader=loader,
        registry=registry,
        tables_dir=dataset / "tables",
        manifest_path=dataset / "table-manifest.json",
        ddl_path=DDL,
        only=only,
        apply=True,
    )

    first = load_data(profile(), **kwargs)
    second = load_data(profile(), **kwargs)

    assert first.rows_loaded() == second.rows_loaded()
    assert {entry.table: entry.rows_after for entry in first.tables} == {
        entry.table: entry.rows_after for entry in second.tables
    }


def test_loaded_row_counts_match_the_manifest(registry, dataset) -> None:  # type: ignore[no-untyped-def]
    from globalmart.dataload import expected_row_counts

    loader = FakeLoader(existing=set(registry.names()))
    expected = expected_row_counts(dataset / "table-manifest.json")

    report = load_data(
        profile(),
        apply=True,
        loader=loader,
        registry=registry,
        tables_dir=dataset / "tables",
        manifest_path=dataset / "table-manifest.json",
        ddl_path=DDL,
    )

    actual = {entry.table: entry.rows_after for entry in report.tables}
    assert actual == expected
    assert sum(actual.values()) > 0


def test_truncation_happens_in_reverse_dependency_order(registry, dataset) -> None:  # type: ignore[no-untyped-def]
    loader = FakeLoader(existing=set(registry.names()))
    load_data(
        profile(),
        apply=True,
        loader=loader,
        registry=registry,
        tables_dir=dataset / "tables",
        manifest_path=dataset / "table-manifest.json",
        ddl_path=DDL,
    )

    truncations = [c.split(":", 1)[1] for c in loader.calls if c.startswith("truncate:")]
    assert truncations == list(reversed(registry.load_order))


def test_tampered_data_is_refused_before_any_write(tmp_path: Path, registry, dataset) -> None:  # type: ignore[no-untyped-def]
    staging = tmp_path / "tables"
    staging.mkdir()
    for source in (dataset / "tables").glob("*.csv.gz"):
        (staging / source.name).write_bytes(source.read_bytes())
    with gzip.open(staging / "dim_store.csv.gz", "wb") as handle:
        handle.write(b"store_id\nnonsense\n")

    loader = FakeLoader(existing=set(registry.names()))
    with pytest.raises(DataIntegrityError):
        load_data(
            profile(),
            apply=True,
            loader=loader,
            registry=registry,
            tables_dir=staging,
            manifest_path=dataset / "table-manifest.json",
            ddl_path=DDL,
        )
    assert loader.calls == []


def test_the_manifest_digests_are_actually_correct(dataset) -> None:
    """Guard: a manifest built from the same wrong bytes would verify vacuously.

    Now checked against a *generated* manifest, which is the only kind that carries digests
    since ADR 008. The committed contract has no bytes to vouch for.
    """
    manifest = json.loads((dataset / "table-manifest.json").read_text(encoding="utf-8"))
    entry = manifest["tables"]["dim_store"]

    with gzip.open(dataset / "tables" / "dim_store.csv.gz", "rb") as handle:
        raw = handle.read()

    import csv
    import io

    reader = csv.reader(io.StringIO(raw.decode("utf-8")))
    header = next(reader)
    rows = sum(1 for _ in reader)

    assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
    assert rows == entry["rows"]
    assert header == entry["columns"]


# --- freshness (ADR 008: something has to keep the warehouse current) ---------


def test_an_empty_warehouse_is_stale(registry) -> None:  # type: ignore[no-untyped-def]
    from globalmart.dataload import check_freshness

    result = check_freshness(
        profile(), registry=registry, manifest_path=MANIFEST, loader=FakeLoader()
    )

    assert not result.present
    assert result.stale()


def test_recent_data_is_current(registry) -> None:  # type: ignore[no-untyped-def]
    from datetime import date

    from globalmart.dataload import check_freshness, choose_probe

    probe = choose_probe(registry, json.loads(MANIFEST.read_text(encoding="utf-8")))
    assert probe is not None
    loader = FakeLoader(existing={probe[0]}, latest="2026-09-10")

    result = check_freshness(
        profile(),
        registry=registry,
        manifest_path=MANIFEST,
        loader=loader,
        today=date(2026, 9, 20),
    )

    assert result.present
    assert result.age_days == 10
    assert not result.stale()


def test_data_beyond_the_age_limit_is_stale(registry) -> None:  # type: ignore[no-untyped-def]
    """The 21-month staleness that started all this, as a test rather than a discovery."""
    from datetime import date

    from globalmart.dataload import check_freshness, choose_probe

    probe = choose_probe(registry, json.loads(MANIFEST.read_text(encoding="utf-8")))
    assert probe is not None
    loader = FakeLoader(existing={probe[0]}, latest="2024-12-28")

    result = check_freshness(
        profile(),
        registry=registry,
        manifest_path=MANIFEST,
        loader=loader,
        today=date(2026, 9, 20),
    )

    assert result.stale()
    assert result.age_days is not None and result.age_days > 600


def test_the_probe_is_a_dated_table_chosen_from_the_contract(registry) -> None:  # type: ignore[no-untyped-def]
    """Chosen by size and declared type, so no table is named anywhere."""
    from globalmart.dataload import choose_probe

    probe = choose_probe(registry, json.loads(MANIFEST.read_text(encoding="utf-8")))

    assert probe is not None
    table, column = probe
    declared = {c.name: c.sql_type.upper() for c in registry.require(table).columns}
    assert declared[column].startswith("DATE")


def test_a_table_missing_a_declared_column_is_refused_before_any_truncate(registry, dataset) -> None:  # type: ignore[no-untyped-def]
    """The 2026-09-21 incident, as a test.

    Adding the wdf__ columns to the DDL left the warehouse behind, because `apply_ddl`
    creates with IF NOT EXISTS and never alters an existing table. The mismatch surfaced at
    insert time — after the truncate — so 215 tables were emptied, 215 inserts refused, and
    the live workspaces read nothing until the schema was dropped and recreated.
    """
    stale = {
        name: tuple(c for c in registry.require(name).column_names() if not c.startswith("wdf__"))
        for name in registry.names()
    }
    loader = FakeLoader(existing=set(registry.names()), live_columns=stale)

    with pytest.raises(DataIntegrityError) as caught:
        load_data(
            profile(),
            apply=True,
            loader=loader,
            registry=registry,
            tables_dir=dataset / "tables",
            manifest_path=dataset / "table-manifest.json",
            ddl_path=DDL,
        )

    assert "wdf__" in str(caught.value)
    assert "Nothing was truncated" in str(caught.value)
    assert not [call for call in loader.calls if call.startswith("truncate:")], (
        "the guard fired but something was truncated anyway, which is the whole failure"
    )


def test_a_matching_schema_loads_normally(registry, dataset) -> None:  # type: ignore[no-untyped-def]
    """The guard must not refuse a warehouse that is actually up to date."""
    current = {name: registry.require(name).column_names() for name in registry.names()}
    loader = FakeLoader(existing=set(registry.names()), live_columns=current)

    report = load_data(
        profile(),
        apply=True,
        loader=loader,
        registry=registry,
        tables_dir=dataset / "tables",
        manifest_path=dataset / "table-manifest.json",
        ddl_path=DDL,
    )

    assert report.column_drift == ()
    assert all(entry.loaded for entry in report.tables)
