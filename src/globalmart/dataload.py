"""Load GlobalMart's rows into a warehouse, idempotently and only where allowed.

Two defects made the predecessor's data unusable for a cold rebuild, and both are fixed
here rather than mitigated:

**It doubled.** `INSERT INTO {schema}.{table} SELECT * FROM read_csv_auto(...)` with no
truncate, so a second load left every table with twice the rows and no error. Here every
table is emptied immediately before it is filled, so loading twice is loading once.

**It could not be restored.** The rows lived only in a bucket this project does not own.
They are now committed under `data/tables/`, 2.3 MB gzipped, so a clone *is* the data.

`put_declarative_workspace` gets a backup before it overwrites (ADR 002); a warehouse load
cannot, because there is nowhere to put a copy of a warehouse. ADR 004 substitutes three
guards, all enforced before a single row is deleted:

1. **`data_owned`** — the profile must declare the schema is this repo's to overwrite. A
   mistyped `--target` then costs an error message rather than someone else's data.
2. **Registry subset** — if the schema holds a table this repo does not know, the load is
   refused and the table is named. Truncating only what we recognise would still be a
   partial wipe of a warehouse we clearly do not understand.
3. **Census** — row counts for every table are read *before* anything is truncated and kept
   in the report, so what was overwritten is knowable afterwards.

And, as everywhere else, `--apply` is the only path to a write.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from globalmart.config import GlobalmartError, TargetProfile
from globalmart.loaders import make_loader
from globalmart.loaders.base import LoadReport, TableLoad, WarehouseLoader
from globalmart.registry import (
    DEFAULT_DDL_PATH,
    DEFAULT_MANIFEST_PATH,
    DEFAULT_TABLES_DIR,
    TableRegistry,
    build_registry,
    render_ddl,
)


class DataOwnershipError(GlobalmartError):
    """The profile has not declared this warehouse schema as owned by this repo."""


class DataIntegrityError(GlobalmartError):
    """The committed data does not match the committed manifest."""


@dataclass(frozen=True)
class VerifyResult:
    """What `data verify` found."""

    tables: int
    rows: int
    mismatches: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()

    def ok(self) -> bool:
        return not (self.mismatches or self.missing or self.extra)

    def summary_lines(self) -> list[str]:
        lines = [f"tables            : {self.tables}", f"rows              : {self.rows:,}"]
        for label, entries in (
            ("MISMATCHED", self.mismatches),
            ("MISSING", self.missing),
            ("UNEXPECTED", self.extra),
        ):
            if entries:
                lines.append(f"{label:18s}: {', '.join(entries)}")
        return lines


def load_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise DataIntegrityError(f"No data manifest at {path}")
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise DataIntegrityError(
            f"{path}: manifest version {manifest.get('version')!r} is not supported"
        )
    return manifest


def read_table_csv(tables_dir: Path, table: str) -> bytes:
    """The uncompressed CSV bytes for one table."""
    path = Path(tables_dir) / f"{table}.csv.gz"
    if not path.exists():
        raise DataIntegrityError(f"No data file for table {table!r} at {path}")
    with gzip.open(path, "rb") as handle:
        return handle.read()


def verify_data(
    *, tables_dir: Path = DEFAULT_TABLES_DIR, manifest_path: Path = DEFAULT_MANIFEST_PATH
) -> VerifyResult:
    """Check every committed table against the manifest.

    Hashes the **uncompressed** bytes: gzip embeds a timestamp, so a digest over the
    compressed file would change on every re-compression and the check would be theatre.
    """
    manifest = load_manifest(manifest_path)
    expected: dict[str, Any] = manifest["tables"]

    present = {path.name[: -len(".csv.gz")] for path in Path(tables_dir).glob("*.csv.gz")}
    missing = tuple(sorted(set(expected) - present))
    extra = tuple(sorted(present - set(expected)))

    mismatches: list[str] = []
    rows = 0
    for table in sorted(set(expected) & present):
        raw = read_table_csv(tables_dir, table)
        entry = expected[table]
        digest = hashlib.sha256(raw).hexdigest()
        if digest != entry["sha256"]:
            mismatches.append(f"{table} (sha256)")
            continue
        rows += int(entry["rows"])

    return VerifyResult(
        tables=len(present),
        rows=rows,
        mismatches=tuple(mismatches),
        missing=missing,
        extra=extra,
    )


def _census(loader: WarehouseLoader, schema: str, tables: list[str], present: set[str]) -> dict[str, int]:
    return {table: loader.row_count(schema, table) for table in tables if table in present}


def load_data(
    profile: TargetProfile,
    *,
    apply: bool = False,
    only: set[str] | None = None,
    tables_dir: Path = DEFAULT_TABLES_DIR,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    ddl_path: Path = DEFAULT_DDL_PATH,
    model: Any | None = None,
    loader: WarehouseLoader | None = None,
    registry: TableRegistry | None = None,
) -> LoadReport:
    """Apply the DDL, then truncate-then-load every table. Rehearsal unless ``apply``."""
    if apply and not profile.data_owned:
        raise DataOwnershipError(
            f"Profile {profile.name!r} does not declare `data_owned: true`, and loading "
            "truncates every table it knows. Set it in config/targets.yaml only for a "
            "warehouse schema this repo is allowed to overwrite (ADR 004)."
        )

    verification = verify_data(tables_dir=tables_dir, manifest_path=manifest_path)
    if not verification.ok():
        raise DataIntegrityError(
            "the committed data does not match the manifest:\n  "
            + "\n  ".join(verification.summary_lines())
        )

    table_registry = registry or build_registry(ddl_path, model=model)
    schema = profile.datasource_schema

    wanted = [name for name in table_registry.load_order if only is None or name in only]
    if only:
        unknown = sorted(only - table_registry.names())
        if unknown:
            raise GlobalmartError(f"--only names unknown table(s): {', '.join(unknown)}")

    owned_loader = loader or make_loader(profile)
    report = LoadReport(
        target=profile.name,
        schema=schema,
        warehouse=getattr(owned_loader, "warehouse", "unknown"),
        applied=apply,
    )

    owned_loader.connect()
    try:
        if apply:
            owned_loader.apply_ddl(render_ddl(ddl_path, schema))

        present = owned_loader.existing_tables(schema)

        # Guard 2: a schema holding something we do not recognise is not a schema we should
        # be emptying, even in part.
        unknown_present = sorted(present - table_registry.names())
        report.unknown_tables = tuple(unknown_present)
        if unknown_present:
            raise DataOwnershipError(
                f"schema {schema!r} on {profile.name!r} contains "
                f"{len(unknown_present)} table(s) this repo does not know: "
                f"{', '.join(unknown_present[:10])}"
                f"{' ...' if len(unknown_present) > 10 else ''}. "
                "Refusing to truncate anything — check the profile's datasource_schema."
            )

        # Guard 3: the census is taken before any write, and in a rehearsal too.
        report.census = _census(owned_loader, schema, wanted, present)

        if not apply:
            report.tables = [
                TableLoad(table=table, rows_before=report.census.get(table, 0)) for table in wanted
            ]
            return report

        with tempfile.TemporaryDirectory(prefix="globalmart-load-") as scratch:
            staging = Path(scratch)
            # Truncate everything first, in reverse dependency order, before loading
            # anything — so a warehouse that does enforce constraints never sees a
            # half-empty parent while a child still references it.
            for table in reversed(wanted):
                owned_loader.truncate(schema, table)

            for table in wanted:
                entry = TableLoad(table=table, rows_before=report.census.get(table, 0))
                try:
                    csv_path = staging / f"{table}.csv"
                    csv_path.write_bytes(read_table_csv(tables_dir, table))
                    entry.rows_after = owned_loader.load_csv(
                        schema, table, csv_path, table_registry.require(table).column_names()
                    )
                    entry.loaded = True
                    csv_path.unlink()
                except Exception as error:  # noqa: BLE001 - reported per table, then raised
                    entry.error = str(error)
                report.tables.append(entry)
    finally:
        owned_loader.close()

    failed = [entry for entry in report.tables if entry.error]
    if failed:
        listed = "\n  ".join(f"{entry.table}: {entry.error}" for entry in failed[:10])
        raise GlobalmartError(f"{len(failed)} table(s) failed to load:\n  {listed}")

    return report


def expected_row_counts(manifest_path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, int]:
    """What each table should hold after a load — the oracle for idempotency checks."""
    manifest = load_manifest(manifest_path)
    return {table: int(entry["rows"]) for table, entry in manifest["tables"].items()}


def csv_columns(tables_dir: Path, table: str) -> tuple[str, ...]:
    """The header of a committed table, for checking the CSV against the DDL."""
    raw = read_table_csv(tables_dir, table)
    reader = csv.reader(io.StringIO(raw.decode("utf-8")))
    return tuple(next(reader, []))
