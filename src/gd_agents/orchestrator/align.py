"""The lanes' own rows, placed side by side on the key they agreed on.

The merged answer narrates a comparison — "spend peaked in September, NPS peaked in June" —
and a reader reasonably wants to see the two series that sentence was read off. This builds
that table.

**It is alignment, not a join, and the distinction is the whole reason this is safe.** No
row of one workspace is matched to a row of another by any business key. Each lane returned
an independent series broken down by the same time grain, and the series are listed against
that grain in one table, each column labelled with the workspace it came from. That is
exactly the claim the merge makes in prose; rendering it as a table adds no claim.

Two rules keep it honest:

**Only the grain the checks agreed on.** A lane that returned two charts contributes only
the one at the shared grain — its campaign ranking has no place in a monthly table and
putting it there would imply a correspondence that does not exist.

**A missing cell is blank, never zero.** One lane covering five months against another's six
is a gap in coverage, and a zero would read as a measured value of nothing.

Values are the lane's `formattedRows` as sent, so the table and the answer above it show a
number the same way.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from gd_agents.artifacts import chart_pairs, columns_of, grain_of
from gd_agents.lane import Answer


@dataclass
class Column:
    """One metric from one workspace, at the shared grain."""

    workspace: str
    name: str
    values: dict[str, str] = field(default_factory=dict)
    """key -> the value as the workspace formatted it."""


@dataclass
class Aligned:
    grain: str = ""
    keys: tuple[str, ...] = ()
    columns: tuple[Column, ...] = ()

    def usable(self) -> bool:
        """Worth showing only when it compares something: two columns, from two lanes."""
        return len(self.keys) > 1 and len({c.workspace for c in self.columns}) > 1

    def payload(self) -> dict[str, Any]:
        return {
            "grain": self.grain,
            "columns": [{"workspace": c.workspace, "name": c.name} for c in self.columns],
            "rows": [
                {"key": key, "cells": [c.values.get(key, "") for c in self.columns]}
                for key in self.keys
            ],
        }


def _rows_of(data: dict[str, Any] | None) -> list[Any]:
    source = (data or {}).get("formattedRows") or (data or {}).get("rows") or []
    return list(source) if isinstance(source, list) else []


def _cell(row: Any, name: str, index: int) -> str:
    if isinstance(row, dict):
        value = row.get(name)
    elif isinstance(row, list) and index < len(row):
        value = row[index]
    else:
        value = None
    return "" if value is None else str(value)


def align(answers: Sequence[Answer], grain: str | None) -> Aligned:
    """Every lane's series at `grain`, against the keys they share.

    Key order is first-seen rather than sorted: the agent returned its months in order, and
    sorting an arbitrary attribute's labels alphabetically would reorder a series that was
    already meaningfully ordered.
    """
    if not grain:
        return Aligned()

    keys: list[str] = []
    columns: list[Column] = []

    for answer in answers:
        if not answer.ok() or not answer.shape.returned_data:
            continue
        for visualization, data in chart_pairs(answer.artifacts):
            if grain_of(visualization) != grain:
                continue
            attribute_names, metric_names = columns_of(data)
            if not attribute_names or not metric_names:
                continue
            rows = _rows_of(data)
            if not rows:
                continue

            key_name = attribute_names[0]
            built = [Column(workspace=answer.workspace, name=name) for name in metric_names]
            for row in rows:
                key = _cell(row, key_name, 0)
                if not key:
                    continue
                if key not in keys:
                    keys.append(key)
                for offset, column in enumerate(built):
                    column.values[key] = _cell(row, column.name, len(attribute_names) + offset)
            columns += [c for c in built if c.values]

    return Aligned(grain=grain, keys=tuple(keys), columns=tuple(columns))


def shared_grain(answers: Sequence[Answer]) -> str | None:
    """The grain every reporting lane returned, when there is exactly one such.

    Mirrors `shared_dimension`'s overlap rule rather than re-deriving it: with more than one
    grain in common, picking one here would be this module choosing what the answer is about.
    """
    reported = [set(a.shape.grains) or ({a.shape.grain} if a.shape.grain else set()) for a in answers]
    reported = [grains for grains in reported if grains]
    if len(reported) < 2:
        return None
    common = set.intersection(*reported)
    return next(iter(common)) if len(common) == 1 else None
