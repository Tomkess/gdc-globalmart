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
    verify_data,
)
from globalmart.registry import build_registry

REPO = Path(__file__).resolve().parents[1]
DDL = REPO / "data" / "ddl" / "globalmart.sql"
TABLES = REPO / "data" / "tables"
MANIFEST = REPO / "data" / "table-manifest.json"


class FakeLoader:
    """A warehouse that appends, so a missing truncate is visible as doubling."""

    warehouse = "fake"

    def __init__(self, *, existing: set[str] | None = None) -> None:
        self.rows: dict[str, int] = dict.fromkeys(existing or set(), 0)
        self.calls: list[str] = []
        self.ddl_applied = False

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


pytestmark = pytest.mark.skipif(not TABLES.exists(), reason="committed data not present")


@pytest.fixture(scope="module")
def registry():  # type: ignore[no-untyped-def]
    return build_registry(DDL)


# --- the committed artifact ---------------------------------------------------


def test_the_committed_data_matches_the_manifest() -> None:
    result = verify_data(tables_dir=TABLES, manifest_path=MANIFEST)

    assert result.ok()
    assert result.tables == 215
    assert result.rows == 174_372


def test_a_tampered_table_is_detected(tmp_path: Path) -> None:
    """The digest covers the uncompressed bytes, so re-gzipping alone is not a change."""
    staging = tmp_path / "tables"
    staging.mkdir()
    for source in TABLES.glob("*.csv.gz"):
        (staging / source.name).write_bytes(source.read_bytes())

    victim = staging / "dim_store.csv.gz"
    with gzip.open(victim, "rb") as handle:
        content = handle.read()
    with gzip.open(victim, "wb") as handle:
        handle.write(content + b"tampered,with,a,row,of,nonsense,0\n")

    result = verify_data(tables_dir=staging, manifest_path=MANIFEST)

    assert not result.ok()
    assert any("dim_store" in entry for entry in result.mismatches)


def test_recompressing_is_not_a_change(tmp_path: Path) -> None:
    """Guard against the digest being over the compressed bytes, which gzip timestamps."""
    staging = tmp_path / "tables"
    staging.mkdir()
    for source in TABLES.glob("*.csv.gz"):
        with gzip.open(source, "rb") as handle:
            raw = handle.read()
        with gzip.open(staging / source.name, "wb") as handle:
            handle.write(raw)

    assert verify_data(tables_dir=staging, manifest_path=MANIFEST).ok()


def test_a_missing_table_file_is_reported(tmp_path: Path) -> None:
    staging = tmp_path / "tables"
    staging.mkdir()
    for source in TABLES.glob("*.csv.gz"):
        if source.name != "dim_store.csv.gz":
            (staging / source.name).write_bytes(source.read_bytes())

    result = verify_data(tables_dir=staging, manifest_path=MANIFEST)

    assert result.missing == ("dim_store",)


def test_an_unsupported_manifest_version_is_refused(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["version"] = 2
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(DataIntegrityError, match="version"):
        verify_data(tables_dir=TABLES, manifest_path=path)


def test_the_manifest_records_what_was_manufactured() -> None:
    """`fact_search_event` is the one table whose rows are not inherited — say so."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["synthesised"] == ["fact_search_event"]
    assert manifest["tables"]["fact_search_event"]["rows"] > 0


def test_every_committed_csv_matches_its_ddl_columns(registry) -> None:  # type: ignore[no-untyped-def]
    """A CSV whose columns drifted from the DDL would load values into the wrong columns."""
    from globalmart.dataload import csv_columns

    mismatched = [
        table
        for table in sorted(registry.names())
        if csv_columns(TABLES, table) != registry.require(table).column_names()
    ]
    assert mismatched == []


# --- the ADR 004 guards -------------------------------------------------------


def test_a_load_is_refused_without_data_owned(registry) -> None:  # type: ignore[no-untyped-def]
    loader = FakeLoader()

    with pytest.raises(DataOwnershipError, match="data_owned"):
        load_data(
            profile(data_owned=False),
            apply=True,
            loader=loader,
            registry=registry,
            tables_dir=TABLES,
            manifest_path=MANIFEST,
            ddl_path=DDL,
        )
    assert loader.calls == []


def test_a_rehearsal_is_allowed_without_data_owned(registry) -> None:  # type: ignore[no-untyped-def]
    """Reading is always safe; it is truncating that needs permission."""
    loader = FakeLoader()
    report = load_data(
        profile(data_owned=False),
        loader=loader,
        registry=registry,
        tables_dir=TABLES,
        manifest_path=MANIFEST,
        ddl_path=DDL,
    )

    assert report.applied is False
    assert not any(call.startswith("truncate") for call in loader.calls)


def test_an_unknown_table_in_the_schema_refuses_the_whole_load(registry) -> None:  # type: ignore[no-untyped-def]
    """A mistyped schema must not cost someone else their data."""
    loader = FakeLoader(existing={"dim_store", "somebody_elses_table"})

    with pytest.raises(DataOwnershipError, match="somebody_elses_table"):
        load_data(
            profile(),
            apply=True,
            loader=loader,
            registry=registry,
            tables_dir=TABLES,
            manifest_path=MANIFEST,
            ddl_path=DDL,
        )
    assert not any(call.startswith("truncate") for call in loader.calls)


def test_the_census_is_taken_before_anything_is_truncated(registry) -> None:  # type: ignore[no-untyped-def]
    loader = FakeLoader(existing=set(registry.names()))
    loader.rows["dim_store"] = 42

    report = load_data(
        profile(),
        apply=True,
        loader=loader,
        registry=registry,
        tables_dir=TABLES,
        manifest_path=MANIFEST,
        ddl_path=DDL,
        only={"dim_store"},
    )

    assert report.census["dim_store"] == 42
    assert report.tables[0].rows_before == 42


def test_the_census_is_taken_in_a_rehearsal_too(registry) -> None:  # type: ignore[no-untyped-def]
    loader = FakeLoader(existing=set(registry.names()))
    loader.rows["dim_store"] = 7

    report = load_data(
        profile(),
        loader=loader,
        registry=registry,
        tables_dir=TABLES,
        manifest_path=MANIFEST,
        ddl_path=DDL,
        only={"dim_store"},
    )

    assert report.census["dim_store"] == 7
    assert report.rows_overwritten() == 7


# --- the two defects ----------------------------------------------------------


def test_loading_twice_does_not_double(registry) -> None:  # type: ignore[no-untyped-def]
    """The predecessor's defect. The fake appends, so a missing truncate doubles here too."""
    loader = FakeLoader(existing=set(registry.names()))
    only = {"dim_store", "dim_product", "fact_search_event"}
    kwargs: dict[str, Any] = dict(
        loader=loader,
        registry=registry,
        tables_dir=TABLES,
        manifest_path=MANIFEST,
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


def test_loaded_row_counts_match_the_manifest(registry) -> None:  # type: ignore[no-untyped-def]
    from globalmart.dataload import expected_row_counts

    loader = FakeLoader(existing=set(registry.names()))
    expected = expected_row_counts(MANIFEST)

    report = load_data(
        profile(),
        apply=True,
        loader=loader,
        registry=registry,
        tables_dir=TABLES,
        manifest_path=MANIFEST,
        ddl_path=DDL,
    )

    actual = {entry.table: entry.rows_after for entry in report.tables}
    assert actual == expected
    assert sum(actual.values()) == 174_372


def test_truncation_happens_in_reverse_dependency_order(registry) -> None:  # type: ignore[no-untyped-def]
    loader = FakeLoader(existing=set(registry.names()))
    load_data(
        profile(),
        apply=True,
        loader=loader,
        registry=registry,
        tables_dir=TABLES,
        manifest_path=MANIFEST,
        ddl_path=DDL,
    )

    truncations = [c.split(":", 1)[1] for c in loader.calls if c.startswith("truncate:")]
    assert truncations == list(reversed(registry.load_order))


def test_tampered_data_is_refused_before_any_write(tmp_path: Path, registry) -> None:  # type: ignore[no-untyped-def]
    staging = tmp_path / "tables"
    staging.mkdir()
    for source in TABLES.glob("*.csv.gz"):
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
            manifest_path=MANIFEST,
            ddl_path=DDL,
        )
    assert loader.calls == []


def test_the_manifest_digests_are_actually_correct() -> None:
    """Guard: a manifest built from the same wrong bytes would verify vacuously."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entry = manifest["tables"]["dim_store"]

    with gzip.open(TABLES / "dim_store.csv.gz", "rb") as handle:
        raw = handle.read()

    import csv
    import io

    reader = csv.reader(io.StringIO(raw.decode("utf-8")))
    header = next(reader)
    rows = sum(1 for _ in reader)

    assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
    assert rows == entry["rows"]
    assert header == entry["columns"]
