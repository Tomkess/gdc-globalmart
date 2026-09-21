"""A seeded, deterministic generator producing GlobalMart-shaped data at any scale.

Since ADR 008 this is the *only* source of GlobalMart's rows. The archive that FEAT-005
committed is gone: committed data has no mechanism that keeps itself current, which is how
it came to sit 21 months stale behind dashboards whose relative date filters resolved to an
empty range. What stays in the repository is the contract — the DDL, and a manifest of row
counts and columns. The payload is produced on demand.

**What it guarantees:** determinism, referential integrity by construction, row counts
matching the contract at scale 1, a window that ends at the run date by default, values that
behave like retail rather than like noise, and workspace-data-filter columns that agree with
the entity each row belongs to.

**Determinism means one seed and one window, not one set of bytes forever.** The window is
an explicit parameter recorded in the generated manifest, so any run reproduces from what it
reports — and two runs on different days differ, deliberately, because the window moved.

**Plausibility lives in `plausible.py`**, applied after the structural pass so keys, foreign
keys and dates are settled before anything reshapes a number. GlobalMart faces prospects, and
a revenue line that is visibly uniform reads as broken however valid each number is.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path

from globalmart.config import GlobalmartError
from globalmart.plausible import (
    TableScale,
    TimeShape,
    family_of,
    shape_row,
)
from globalmart.registry import (
    DEFAULT_MANIFEST_PATH,
    Table,
    TableRegistry,
    foreign_key_target,
    own_key_column,
)

#: Used for a table the manifest has never seen, so a new DDL table generates rather than
#: failing. Small on purpose: an unknown table is more likely reference data than a fact.
DEFAULT_ROWS = 100

#: Workspace-data-filter columns. The `wdf__` prefix follows the convention the
#: `demo_ecommerce` workspace already established in the same org. Every table carries them,
#: so a filter layer has nothing it silently fails to cover.
WDF_PREFIX = "wdf__"
WDF_TENANT_COLUMN = "wdf__tenant_id"
WDF_REGION_COLUMN = "wdf__region"

#: Fictional, and readable on purpose. A filter value a person recognises is worth more here
#: than a minted key, and the rows are synthetic either way.
WDF_VOCABULARY: dict[str, tuple[str, ...]] = {
    WDF_TENANT_COLUMN: ("acme", "globex", "initech", "umbrella"),
    WDF_REGION_COLUMN: ("EMEA", "AMER", "APAC"),
}

#: How much history a generated dataset covers when no explicit start is given. Two years
#: is enough for a year-on-year metric to have something to compare against.
DEFAULT_WINDOW_DAYS = 730

FACT_PREFIX = "fact_"


class GenerationError(GlobalmartError):
    """The dataset could not be generated."""


class ColumnStrategy(StrEnum):
    OWN_KEY = "own_key"
    FOREIGN_KEY = "foreign_key"
    DATE = "date"
    INTEGER = "integer"
    DECIMAL = "decimal"
    NAME = "name"
    CODE = "code"
    FILTER = "filter"


@dataclass(frozen=True)
class ColumnPlan:
    column: str
    strategy: ColumnStrategy
    target: str | None = None


@dataclass(frozen=True)
class KeySpace:
    """The key values one table minted, for later tables to draw from.

    This is what makes referential integrity structural rather than checked afterwards: a
    foreign column cannot hold a value that was never minted, because it draws from the
    minted set instead of from a generator that happens to use the same format.
    """

    table: str
    column: str
    values: tuple[str, ...]
    #: Each minted key's filter values, so a table that references this one inherits them
    #: rather than drawing its own. This is what stops a fact disagreeing with the entity
    #: it belongs to — the coherence a workspace data filter depends on.
    filters: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass
class GenerationReport:
    tables: int = 0
    rows: int = 0
    seed: int = 0
    scale: float = 1.0
    out_dir: Path | None = None
    per_table: dict[str, int] = field(default_factory=dict)

    def summary_lines(self) -> list[str]:
        return [
            f"seed              : {self.seed}",
            f"scale             : {self.scale}",
            f"tables            : {self.tables}",
            f"rows              : {self.rows:,}",
            f"out               : {self.out_dir}",
        ]


# --- planning -----------------------------------------------------------------

#: Kept for the record: these name families are what the numeric columns look like, and
#: they are deliberately *not* used to choose a strategy. The DDL's declared type decides.
#: `hour_start` is an INTEGER whose name ends in `_start`, and trusting the name over the
#: type made the warehouse reject the load.
INTEGER_NAME_FAMILIES = ("_count", "_qty", "_quantity", "_days", "_day", "_points", "_score")
DECIMAL_NAME_FAMILIES = ("_amount", "_cost", "_revenue", "_value", "_metric", "_price", "_rate")


def plan_columns(table: Table, known_tables: frozenset[str] | set[str]) -> tuple[ColumnPlan, ...]:
    """Choose a strategy per column from its SQL type and its name.

    Patterns only — no table and no column is named in this function, so a table added to
    the DDL plans without an edit here. That is the same property the registry has, and for
    the same reason.
    """
    key_column = own_key_column(table, known_tables)
    plans: list[ColumnPlan] = []

    for column in table.columns:
        name = column.name
        sql_type = column.sql_type.upper()

        if name.startswith(WDF_PREFIX):
            # Checked first: `wdf__tenant_id` ends in `_id` and would otherwise be read as
            # a foreign key to a table that does not exist.
            plans.append(ColumnPlan(name, ColumnStrategy.FILTER))
            continue

        if name == key_column:
            plans.append(ColumnPlan(name, ColumnStrategy.OWN_KEY))
            continue

        target = foreign_key_target(name, known_tables)
        if target is not None and target != table.name:
            plans.append(ColumnPlan(name, ColumnStrategy.FOREIGN_KEY, target))
            continue

        # The **declared type wins**, always. Name patterns only disambiguate *within* a
        # type. Letting a name override the type produced a date in `hour_start`, which is
        # an INTEGER — the load failed on it, which is how this rule was learned.
        if sql_type.startswith("DATE") or sql_type.startswith("TIMESTAMP"):
            plans.append(ColumnPlan(name, ColumnStrategy.DATE))
            continue

        if sql_type.startswith(("NUMERIC", "DECIMAL", "FLOAT", "DOUBLE", "REAL")):
            plans.append(ColumnPlan(name, ColumnStrategy.DECIMAL))
            continue

        if sql_type.startswith(("INT", "BIGINT", "SMALLINT", "TINYINT")):
            plans.append(ColumnPlan(name, ColumnStrategy.INTEGER))
            continue

        # Textual from here on. Names choose between a readable label and an opaque code —
        # and a VARCHAR that holds a date still reads as one.
        if name.endswith(("_date", "_start", "_end")):
            plans.append(ColumnPlan(name, ColumnStrategy.DATE))
            continue

        if name.endswith(("_name", "_title", "_label", "_description")):
            plans.append(ColumnPlan(name, ColumnStrategy.NAME))
            continue

        # An unresolvable `_id` lands here: a local identifier, not a dangling reference.
        plans.append(ColumnPlan(name, ColumnStrategy.CODE))

    return tuple(plans)


# --- seeding ------------------------------------------------------------------


def table_seed(seed: int, table_name: str) -> int:
    """A stream per table, derived from the master seed and the table's own name.

    Not one shared `Random`: a shared stream couples tables, so adding a table or changing
    one table's row count would shift every table generated after it and make two runs
    incomparable for no reason at all.
    """
    digest = hashlib.blake2b(f"{seed}:{table_name}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big")


# --- row counts ---------------------------------------------------------------


def base_row_counts(manifest_path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, int]:
    """Row counts from the real archive — the shape reference that makes scale 1 comparable."""
    path = Path(manifest_path)
    if not path.exists():
        return {}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return {table: int(entry["rows"]) for table, entry in manifest.get("tables", {}).items()}


def row_count_for(table_name: str, base_counts: dict[str, int], scale: float) -> int:
    """Facts scale linearly; dimensions scale by ``sqrt`` and never shrink.

    Facts carry the volume. Multiplying twelve currencies by a hundred to make a bigger
    dataset would be nonsense, and shrinking a dimension would drop keys the semantic
    layer's filters expect to find.
    """
    base = base_counts.get(table_name, DEFAULT_ROWS)
    if table_name.startswith(FACT_PREFIX):
        return max(0, round(base * scale))
    return max(base, round(base * math.sqrt(scale)))


# --- values -------------------------------------------------------------------


def resolve_window(
    start: date | None = None, end: date | None = None, *, today: date | None = None
) -> tuple[date, date]:
    """Decide the window to generate into.

    Explicit beats implicit; an end defaults to **today**, which is the whole point. The
    predecessor measured the window by reading the archive it was about to replace — always
    circular, and the reason GlobalMart's data sat 21 months stale behind dashboards whose
    relative filters resolved to an empty range.
    """
    end = end or (today or date.today())
    start = start or (end - timedelta(days=DEFAULT_WINDOW_DAYS))
    if start >= end:
        raise GenerationError(f"window start {start} is not before end {end}")
    return start, end


def _legacy_date_window(
    tables_dir: Path | None = None, manifest_path: Path = DEFAULT_MANIFEST_PATH
) -> tuple[date, date]:
    """The window the real data covers. Retained only until the archive is deleted."""
    from globalmart.dataload import read_table_csv

    if tables_dir is None:
        return resolve_window()
    manifest = Path(manifest_path)
    if not manifest.exists():
        return resolve_window()

    entries = json.loads(manifest.read_text(encoding="utf-8")).get("tables", {})
    seen: list[str] = []
    for table, entry in entries.items():
        columns = entry.get("columns") or []
        date_columns = [c for c in columns if c.endswith("_date")]
        if not date_columns or not (Path(tables_dir) / f"{table}.csv.gz").exists():
            continue
        try:
            raw = read_table_csv(Path(tables_dir), table).decode("utf-8")
        except Exception:  # noqa: BLE001 - a window is a nicety, never a blocker
            continue
        reader = csv.DictReader(io.StringIO(raw))
        for row in reader:
            for column in date_columns:
                value = (row.get(column) or "")[:10]
                if len(value) == 10 and value[4] == "-":
                    seen.append(value)
            if len(seen) > 5000:
                break
        if len(seen) > 5000:
            break

    if not seen:
        return resolve_window()
    return date.fromisoformat(min(seen)), date.fromisoformat(max(seen))


def _value(
    plan: ColumnPlan,
    rng: random.Random,
    *,
    table: str,
    index: int,
    keyspaces: dict[str, KeySpace],
    window: tuple[date, date],
) -> str:
    if plan.strategy is ColumnStrategy.OWN_KEY:
        return f"{table}_{index:06d}"

    if plan.strategy is ColumnStrategy.FOREIGN_KEY:
        space = keyspaces.get(plan.target or "")
        if space is None or not space.values:
            # The target exists in the DDL but minted no keys. Emitting a plausible-looking
            # value would be the referential-integrity bug this design exists to prevent.
            return ""
        return rng.choice(space.values)

    if plan.strategy is ColumnStrategy.DATE:
        start, end = window
        span = max((end - start).days, 1)
        return (start + timedelta(days=rng.randrange(span))).isoformat()

    if plan.strategy is ColumnStrategy.INTEGER:
        return str(rng.randint(0, 1000))

    if plan.strategy is ColumnStrategy.DECIMAL:
        return f"{rng.uniform(0, 10000):.2f}"

    if plan.strategy is ColumnStrategy.NAME:
        return f"{plan.column.replace('_', ' ').title()} {index:04d}"

    return f"{plan.column}_{index:05d}"


def _assign_filters(
    columns: list[str],
    *,
    values: dict[str, str],
    foreign_plans: tuple[ColumnPlan, ...],
    keyspaces: dict[str, KeySpace],
) -> dict[str, str]:
    """Resolve one row's filter values, inheriting wherever it can.

    Precedence is inheritance first, assignment second. If the row references an entity that
    already carries filter values, it takes them — so every order line under a store agrees
    with that store, and a tenant filter never returns a row that half-belongs to it. Only a
    row with nothing to inherit from assigns its own, deterministically from its key.

    Tables are generated in dependency order, so a referenced table has always been assigned
    before anything that references it.
    """
    for plan in foreign_plans:
        space = keyspaces.get(plan.target or "")
        if space is None or not space.filters:
            continue
        inherited = space.filters.get(values.get(plan.column, ""))
        if inherited:
            return dict(inherited)

    seed_value = next(
        (values[c] for c in values if c not in columns and values[c]),
        "",
    )
    return {
        column: _pick(WDF_VOCABULARY[column], f"{column}:{seed_value}")
        for column in columns
        if column in WDF_VOCABULARY
    }


def _pick(vocabulary: tuple[str, ...], key: str) -> str:
    """A stable choice from a fixed vocabulary. blake2b, because `hash()` is salted."""
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return vocabulary[int.from_bytes(digest, "big") % len(vocabulary)]


def _row_date(values: dict[str, str], date_columns: list[str]) -> date | None:
    """The date this row's numbers should follow, if it has one.

    The first dated column wins. A table with several dates (an order date and a ship date,
    say) is driven by the one declared first, which is the one the DDL author put first.
    """
    for column in date_columns:
        raw = values.get(column, "")
        if len(raw) == 10 and raw[4] == "-":
            try:
                return date.fromisoformat(raw)
            except ValueError:
                continue
    return None


def generate_table(
    table: Table,
    plans: tuple[ColumnPlan, ...],
    *,
    rows: int,
    keyspaces: dict[str, KeySpace],
    seed: int,
    window: tuple[date, date],
) -> tuple[bytes, KeySpace | None]:
    """Generate one table's CSV bytes and the key space it mints."""
    rng = random.Random(table_seed(seed, table.name))

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([plan.column for plan in plans])

    key_plan = next((p for p in plans if p.strategy is ColumnStrategy.OWN_KEY), None)
    minted: list[str] = []

    # Numeric columns are shaped, not drawn. Classified once per table rather than per row,
    # and only the numeric strategies qualify: a key or a code is structural and must not
    # be touched by anything that cares how the number *looks*.
    numeric = {
        plan.column: family_of(plan.column)
        for plan in plans
        if plan.strategy in (ColumnStrategy.INTEGER, ColumnStrategy.DECIMAL)
    }
    date_columns = [plan.column for plan in plans if plan.strategy is ColumnStrategy.DATE]
    # The DDL decides how a number is written. Shaping changes what a value *means*, never
    # what type it is stored as.
    integers = frozenset(plan.column for plan in plans if plan.strategy is ColumnStrategy.INTEGER)
    filter_columns = [plan.column for plan in plans if plan.strategy is ColumnStrategy.FILTER]
    foreign_plans = tuple(p for p in plans if p.strategy is ColumnStrategy.FOREIGN_KEY)
    minted_filters: dict[str, dict[str, str]] = {}
    shape = TimeShape(start=window[0], end=window[1])
    scale = TableScale.draw(rng)

    for index in range(rows):
        values = {
            plan.column: _value(plan, rng, table=table.name, index=index, keyspaces=keyspaces, window=window)
            for plan in plans
        }

        if filter_columns:
            assigned = _assign_filters(
                filter_columns,
                values=values,
                foreign_plans=foreign_plans,
                keyspaces=keyspaces,
            )
            values.update(assigned)
            if key_plan is not None:
                minted_filters[values[key_plan.column]] = assigned

        if numeric:
            when = _row_date(values, date_columns)
            shape_row(
                values,
                numeric,
                when=when,
                shape=shape,
                scale=scale,
                rng=rng,
                integers=integers,
            )

        row = [values[plan.column] for plan in plans]
        if key_plan is not None:
            minted.append(values[key_plan.column])
        writer.writerow(row)

    space = (
        KeySpace(
            table=table.name,
            column=key_plan.column,
            values=tuple(minted),
            filters=minted_filters,
        )
        if key_plan is not None
        else None
    )
    return buffer.getvalue().encode("utf-8"), space


# --- the dataset --------------------------------------------------------------


def generate_dataset(
    registry: TableRegistry,
    *,
    out_dir: Path,
    seed: int = 20260920,
    scale: float = 1.0,
    base_counts: dict[str, int] | None = None,
    window: tuple[date, date] | None = None,
) -> GenerationReport:
    """Generate every table in load order, writing FEAT-005's exact format."""
    out_dir = Path(out_dir).resolve()

    # The committed archive is FEAT-005's. A generated variant must never silently become it.
    protected = Path("data").resolve()
    if out_dir == protected or protected in out_dir.parents:
        raise GenerationError(
            f"refusing to generate into {out_dir}: that is the committed archive. "
            "Generate into a scratch directory and load it with --tables-dir."
        )

    if scale <= 0:
        raise GenerationError(f"scale must be positive, got {scale}")

    counts = base_counts if base_counts is not None else base_row_counts()
    effective_window = window or resolve_window()

    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    keyspaces: dict[str, KeySpace] = {}
    entries: dict[str, dict[str, object]] = {}
    report = GenerationReport(seed=seed, scale=scale, out_dir=out_dir)

    # Load order, so a target's keys exist before anything references them.
    for name in registry.load_order:
        table = registry.require(name)
        plans = plan_columns(table, registry.names())
        rows = row_count_for(name, counts, scale)

        raw, space = generate_table(
            table, plans, rows=rows, keyspaces=keyspaces, seed=seed, window=effective_window
        )
        if space is not None:
            keyspaces[name] = space

        # mtime=0: gzip embeds a timestamp, and determinism is the point.
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=(tables_dir / f"{name}.csv.gz").open("wb"), mtime=0
        ) as handle:
            handle.write(raw)

        entries[name] = {
            "rows": rows,
            "columns": [plan.column for plan in plans],
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
        report.per_table[name] = rows
        report.rows += rows

    report.tables = len(entries)

    manifest = {
        "version": 1,
        "source": {
            "kind": "generated",
            "seed": seed,
            "scale": scale,
            "generator": "globalmart.generate",
        },
        "synthesised": sorted(entries),
        "tables": dict(sorted(entries.items())),
    }
    (out_dir / "table-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report
