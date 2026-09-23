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
import datetime as dt
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


@dataclass(frozen=True)
class ContractResult:
    """What `data verify` found in the committed contract.

    ADR 008 moved the rows out of the repository, so there are no bytes to hash here. What
    remains committed is the contract — which tables exist, how many rows each should have,
    and what columns it declares — and the only meaningful offline check is that it agrees
    with the DDL. Byte integrity still exists, but it belongs to a *generated* dataset and
    is checked by `verify_data` at load time.
    """

    tables: int
    rows: int
    missing_from_ddl: tuple[str, ...] = ()
    missing_from_contract: tuple[str, ...] = ()
    column_drift: tuple[str, ...] = ()

    def ok(self) -> bool:
        return not (self.missing_from_ddl or self.missing_from_contract or self.column_drift)

    def summary_lines(self) -> list[str]:
        lines = [
            f"tables            : {self.tables}",
            f"rows contracted   : {self.rows:,}",
        ]
        for label, entries in (
            ("NOT IN DDL", self.missing_from_ddl),
            ("NOT CONTRACTED", self.missing_from_contract),
            ("COLUMN DRIFT", self.column_drift),
        ):
            if entries:
                lines.append(f"{label:18s}: {', '.join(entries)}")
        return lines


def verify_contract(registry: Any, *, manifest_path: Path = DEFAULT_MANIFEST_PATH) -> ContractResult:
    """Check the committed contract against the DDL.

    Runs offline with no credentials, which is the property ADR 007 gave `data verify` and
    this keeps. What it can no longer say is whether the rows are intact, because the rows
    are no longer here.
    """
    manifest = load_manifest(manifest_path)
    contracted: dict[str, Any] = manifest["tables"]
    declared = set(registry.names())

    drift = []
    for table in sorted(set(contracted) & declared):
        columns = tuple(contracted[table].get("columns") or ())
        if columns != registry.require(table).column_names():
            drift.append(table)

    return ContractResult(
        tables=len(contracted),
        rows=sum(int(entry["rows"]) for entry in contracted.values()),
        missing_from_ddl=tuple(sorted(set(contracted) - declared)),
        missing_from_contract=tuple(sorted(declared - set(contracted))),
        column_drift=tuple(drift),
    )


#: How stale the loaded data may be before it is regenerated. A month is long enough that a
#: scheduled run is usually a no-op, and short enough that a dashboard's "last 12 months"
#: never lands in an empty range.
DEFAULT_MAX_AGE_DAYS = 31


@dataclass(frozen=True)
class Freshness:
    """Whether the warehouse holds data, and how recent it is."""

    present: bool
    probe_table: str | None
    probe_column: str | None
    latest: str | None
    age_days: int | None
    max_age_days: int

    def stale(self) -> bool:
        if not self.present or self.latest is None or self.age_days is None:
            return True
        return self.age_days > self.max_age_days

    def summary_lines(self) -> list[str]:
        if not self.present:
            return ["warehouse         : empty — nothing loaded"]
        return [
            f"probe             : {self.probe_table}.{self.probe_column}",
            f"latest date       : {self.latest}",
            f"age               : {self.age_days} days (limit {self.max_age_days})",
            f"verdict           : {'stale' if self.stale() else 'current'}",
        ]


def choose_probe(registry: Any, manifest: dict[str, Any]) -> tuple[str, str] | None:
    """Pick the table whose dates best answer "is this data current?".

    The biggest contracted table that declares a DATE column, with ties broken by name. No
    table is named here: a probe chosen by hand would be one more place that has to be
    edited when the schema moves.
    """
    candidates = []
    for table in sorted(registry.names()):
        if table not in manifest.get("tables", {}):
            continue
        dated = [c.name for c in registry.require(table).columns if c.sql_type.upper().startswith("DATE")]
        if dated:
            candidates.append((int(manifest["tables"][table]["rows"]), table, dated[0]))
    if not candidates:
        return None
    _, table, column = max(candidates, key=lambda item: (item[0], item[1]))
    return table, column


def check_freshness(
    profile: TargetProfile,
    *,
    registry: Any,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    loader: Any | None = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    today: dt.date | None = None,
) -> Freshness:
    """Ask the warehouse whether it holds current data. Read-only."""
    manifest = load_manifest(manifest_path)
    probe = choose_probe(registry, manifest)
    owned = loader if loader is not None else make_loader(profile)

    owned.connect()
    try:
        existing = owned.existing_tables(profile.datasource_schema)
        if probe is None or probe[0] not in existing:
            return Freshness(False, None, None, None, None, max_age_days)
        table, column = probe
        latest = owned.max_value(profile.datasource_schema, table, column)
    finally:
        owned.close()

    if not latest:
        return Freshness(False, table, column, None, None, max_age_days)

    stamp = str(latest)[:10]
    try:
        age = ((today or dt.date.today()) - dt.date.fromisoformat(stamp)).days
    except ValueError:
        return Freshness(True, table, column, stamp, None, max_age_days)
    return Freshness(True, table, column, stamp, age, max_age_days)


def load_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise DataIntegrityError(f"No data manifest at {path}")
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise DataIntegrityError(f"{path}: manifest version {manifest.get('version')!r} is not supported")
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
    recreate_drifted: bool = False,
) -> LoadReport:
    """Apply the DDL, then truncate-then-load every table. Rehearsal unless ``apply``.

    ``recreate_drifted`` lets the load repair a schema whose tables lack a column the DDL
    has since gained, by dropping and rebuilding exactly those tables. Off by default: a
    person running this by hand should be told about drift rather than have tables dropped
    under them. The scheduled workflow turns it on, because the alternative is a job that
    fails every week until somebody opens a SQL console.
    """
    if apply and not profile.data_owned:
        raise DataOwnershipError(
            f"Profile {profile.name!r} does not declare `data_owned: true`, and loading "
            "truncates every table it knows. Set it in config/targets.yaml only for a "
            "warehouse schema this repo is allowed to overwrite (ADR 004)."
        )

    verification = verify_data(tables_dir=tables_dir, manifest_path=manifest_path)
    if not verification.ok():
        raise DataIntegrityError(
            "the committed data does not match the manifest:\n  " + "\n  ".join(verification.summary_lines())
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

        # Guard 3: the warehouse's tables must have the columns the DDL declares.
        #
        # `apply_ddl` creates with IF NOT EXISTS and therefore never alters a table that
        # already exists, so a DDL that gained a column leaves the warehouse behind. Without
        # this check the mismatch surfaces at insert time — which is *after* the truncate,
        # and leaves the schema empty. That happened on 2026-09-21 when the wdf__ columns
        # were added: 215 tables emptied, 215 inserts refused, live workspaces reading
        # nothing until the tables were dropped and recreated.
        drifted: list[str] = []
        for table in wanted:
            if table not in present:
                continue
            live = tuple(owned_loader.columns(schema, table))
            if not live:
                continue
            missing = [c for c in table_registry.require(table).column_names() if c not in live]
            if missing:
                drifted.append(f"{table} (missing {', '.join(missing[:4])})")
        report.column_drift = tuple(drifted)
        if drifted and recreate_drifted and apply:
            # The sanctioned repair. Without it the guard is a dead end: a DDL that gains a
            # column leaves the scheduled workflow failing every week until somebody opens a
            # SQL console, which is exactly the manual step ADR 008 set out to remove.
            #
            # Safe here and nowhere else: the profile owns its data, every table named is one
            # this repo declares, the rows are regenerable from a seed and a window, and the
            # very next thing this function does is load them back.
            names = [entry.split(" ", 1)[0] for entry in drifted]
            for table in names:
                owned_loader.drop_table(schema, table)
            owned_loader.apply_ddl(render_ddl(ddl_path, schema))
            present = owned_loader.existing_tables(schema)
            report.recreated = tuple(names)
            report.column_drift = ()
            drifted = []

        if drifted:
            raise DataIntegrityError(
                f"{len(drifted)} table(s) in schema {schema!r} lack columns the DDL declares:\n  "
                + "\n  ".join(drifted[:10])
                + ("\n  ..." if len(drifted) > 10 else "")
                + "\n\nNothing was truncated. CREATE TABLE IF NOT EXISTS cannot add a column to "
                "an existing table, so the schema must be migrated or dropped and recreated "
                "before loading. Re-run with --recreate-drifted to drop and rebuild exactly "
                "these tables."
            )

        # Guard 4: the census is taken before any write, and in a rehearsal too.
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
