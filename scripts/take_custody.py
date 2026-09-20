"""One-shot: take custody of GlobalMart's row data.

**This is not part of the runtime CLI.** It ran once, on 2026-09-18, and its output —
`data/ddl/globalmart.sql`, `data/tables/*.csv.gz` and `data/table-manifest.json` — is
committed. It is kept so the provenance of those bytes is auditable and so the transfer can
be repeated if the source is ever re-taken.

**Why the source is MotherDuck and not S3.** The spec planned to pull 214 CSVs from
`s3://gdc-services-aisolutions/local-inference/globalmart/`, a bucket this project does not
own. That bucket is not readable with any credentials available here (`InvalidAccessKeyId`),
and the risk row that said "the bucket is lost or access revoked before custody is taken"
had, in effect, already happened. MotherDuck's `gd_demo.globalmart` schema holds the same
214 tables and is what both published orgs actually query, which makes it a *better* source
than the bucket: it is the data the workspaces are known to work against, not an artifact
believed to have produced it.

Usage (needs `MOTHERDUCK_TOKEN` and `duckdb`):

    uv run --with duckdb python scripts/take_custody.py --out data
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import random
import re
import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import Any

SOURCE_DATABASE = "gd_demo"
SOURCE_SCHEMA = "globalmart"

#: The 215th table. `sql_channel_attribution` selects from it, but no DDL and no CSV for it
#: has ever existed — open and unclosed in the predecessor repo, and the reason a cold
#: rebuild could not resolve that dataset. It is the one piece of GlobalMart data that is
#: manufactured here rather than inherited, which is why it lives in its own function with
#: its own seed and is called out in the manifest.
SEARCH_EVENT_TABLE = "fact_search_event"
SEARCH_EVENT_DDL = """
CREATE TABLE IF NOT EXISTS {schema_name}.fact_search_event (
    session_id VARCHAR(255),
    customer_id VARCHAR(255),
    traffic_source VARCHAR(255),
    session_date DATE
);
"""
SEARCH_EVENT_SEED = 20260918
TRAFFIC_SOURCES = ("organic", "paid_search", "social", "email", "direct", "referral")


def connect(token: str) -> Any:
    import duckdb

    return duckdb.connect(f"md:{SOURCE_DATABASE}?motherduck_token={token}")


def export_tables(connection: Any, destination: Path) -> list[str]:
    """Write one CSV per source table into a staging directory."""
    destination.mkdir(parents=True, exist_ok=True)
    tables = [
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables "
            f"WHERE table_schema = '{SOURCE_SCHEMA}' ORDER BY table_name"
        ).fetchall()
    ]
    for table in tables:
        target = destination / f"{table}.csv"
        connection.execute(
            f"COPY (SELECT * FROM {SOURCE_SCHEMA}.{table}) TO '{target}' (HEADER, DELIMITER ',')"
        )
    return tables


def synthesise_search_events(staging: Path, *, rows: int = 4000) -> None:
    """Manufacture `fact_search_event` from customers and dates that already exist.

    Deterministic: one fixed seed, and the customer ids and the date window are read from
    the real exported data rather than invented, so every `customer_id` joins and every
    `session_date` falls inside the period the rest of the dataset covers. A search event
    referencing a customer who does not exist would make `sql_channel_attribution` return
    fewer rows than it should and look like a modelling problem.
    """
    customers = _column_values(staging / "dim_customer.csv", "customer_id")
    if not customers:
        raise SystemExit("dim_customer.csv has no customer_id column — cannot synthesise")

    window_start, window_end = _date_window(staging / "fact_web_order_header.csv")
    span = max((window_end - window_start).days, 1)

    generator = random.Random(SEARCH_EVENT_SEED)
    target = staging / f"{SEARCH_EVENT_TABLE}.csv"
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["session_id", "customer_id", "traffic_source", "session_date"])
        for index in range(rows):
            writer.writerow(
                [
                    f"sess_{index:06d}",
                    generator.choice(customers),
                    generator.choice(TRAFFIC_SOURCES),
                    (window_start + timedelta(days=generator.randrange(span))).isoformat(),
                ]
            )


def _column_values(path: Path, column: str) -> list[str]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or column not in reader.fieldnames:
            return []
        return [row[column] for row in reader if row[column]]


def _date_window(path: Path) -> tuple[date, date]:
    """The date range the rest of the dataset covers, so events land inside it."""
    default = (date(2024, 1, 1), date(2026, 12, 31))
    if not path.exists():
        return default
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        field = next(
            (name for name in (reader.fieldnames or []) if name.endswith("date")), None
        )
        if field is None:
            return default
        seen = [row[field] for row in reader if row.get(field)]
    parsed = sorted(value[:10] for value in seen if re.match(r"^\d{4}-\d{2}-\d{2}", value))
    if not parsed:
        return default
    return date.fromisoformat(parsed[0]), date.fromisoformat(parsed[-1])


def compress_and_measure(staging: Path, tables_dir: Path) -> dict[str, dict[str, Any]]:
    """Gzip each CSV into the committed directory and record what it contains.

    The manifest hashes the **uncompressed** bytes. gzip embeds a timestamp, so hashing the
    compressed file would make the digest change on every re-run and the integrity check
    meaningless.
    """
    if tables_dir.exists():
        shutil.rmtree(tables_dir)
    tables_dir.mkdir(parents=True)

    entries: dict[str, dict[str, Any]] = {}
    for source in sorted(staging.glob("*.csv")):
        table = source.stem
        raw = source.read_bytes()
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=(tables_dir / f"{table}.csv.gz").open("wb"), mtime=0
        ) as out:
            out.write(raw)

        text = raw.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        header = next(reader, [])
        entries[table] = {
            "rows": sum(1 for _ in reader),
            "columns": header,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data", help="the committed data directory")
    parser.add_argument("--staging", default=None, help="where to put intermediate CSVs")
    args = parser.parse_args()

    token = os.environ.get("MOTHERDUCK_TOKEN")
    if not token:
        raise SystemExit("MOTHERDUCK_TOKEN is not set")

    out = Path(args.out)
    staging = Path(args.staging) if args.staging else out / ".staging"

    print(f"Exporting {SOURCE_DATABASE}.{SOURCE_SCHEMA} -> {staging}")
    tables = export_tables(connect(token), staging)
    print(f"  {len(tables)} tables")

    print(f"Synthesising {SEARCH_EVENT_TABLE}")
    synthesise_search_events(staging)

    print(f"Compressing -> {out / 'tables'}")
    entries = compress_and_measure(staging, out / "tables")

    manifest = {
        "version": 1,
        "source": {
            "kind": "motherduck",
            "database": SOURCE_DATABASE,
            "schema": SOURCE_SCHEMA,
            "taken_at": "2026-09-18",
        },
        "synthesised": [SEARCH_EVENT_TABLE],
        "tables": dict(sorted(entries.items())),
    }
    manifest_path = out / "table-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    total_rows = sum(entry["rows"] for entry in entries.values())
    print(f"\n{len(entries)} tables, {total_rows:,} rows")
    print(f"manifest: {manifest_path}")
    shutil.rmtree(staging, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
