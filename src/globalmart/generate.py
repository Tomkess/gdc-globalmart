"""A seeded, deterministic generator producing GlobalMart-shaped data at any scale.

FEAT-005 took custody of the real rows, which solved the problem that actually existed:
the bytes were unowned and unrebuildable. This is the other thing a dataset can need —
being *reshapeable*. It produces data with GlobalMart's structure, keys and date windows at
a chosen scale, in exactly the format FEAT-005's loader already consumes.

**What it guarantees:** determinism (one seed, one output), referential integrity by
construction, row counts matching the real archive at scale 1, and dates inside the window
the real data covers.

**What it does not:** plausibility. The distributions are uniform and unremarkable. A
generated dataset has the right shape and the right keys; it does not have believable
retail behaviour — no seasonality, no relationship between price and margin, no realistic
basket composition. That is deliberate. FEAT-007 was parked precisely because inventing
plausible retail data with no consumer able to judge it is how a dataset quietly becomes
worse while every test still passes. This builds the substrate every use case shares and
stops where judgement would be required.

**It never writes to `data/tables/`.** The committed archive is FEAT-005's. A generated
variant is an alternative you select, never a substitute that appears.
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

#: Used only when the real archive cannot be read. The real window is measured from it.
FALLBACK_WINDOW = (date(2024, 1, 1), date(2026, 12, 31))

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
    key_column = own_key_column(table)
    plans: list[ColumnPlan] = []

    for column in table.columns:
        name = column.name
        sql_type = column.sql_type.upper()

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


def date_window(
    tables_dir: Path | None = None, manifest_path: Path = DEFAULT_MANIFEST_PATH
) -> tuple[date, date]:
    """The window the real data covers, so existing date filters still match rows."""
    from globalmart.dataload import read_table_csv

    if tables_dir is None:
        return FALLBACK_WINDOW
    manifest = Path(manifest_path)
    if not manifest.exists():
        return FALLBACK_WINDOW

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
        return FALLBACK_WINDOW
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

    for index in range(rows):
        row = [
            _value(
                plan, rng, table=table.name, index=index, keyspaces=keyspaces, window=window
            )
            for plan in plans
        ]
        if key_plan is not None:
            minted.append(row[plans.index(key_plan)])
        writer.writerow(row)

    space = (
        KeySpace(table=table.name, column=key_plan.column, values=tuple(minted))
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
    effective_window = window or FALLBACK_WINDOW

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
