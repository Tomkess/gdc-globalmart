# Tests for the plausibility layer: what makes generated numbers survive being looked at.
from __future__ import annotations

import random
import statistics
from datetime import date, timedelta

import pytest

from globalmart.generate import DEFAULT_WINDOW_DAYS, GenerationError, resolve_window
from globalmart.plausible import (
    Family,
    TableScale,
    TimeShape,
    family_of,
    shape_row,
)

WINDOW = (date(2024, 1, 1), date(2026, 1, 1))


def shape() -> TimeShape:
    return TimeShape(start=WINDOW[0], end=WINDOW[1])


def scale() -> TableScale:
    return TableScale.draw(random.Random(11))


def rows_for(columns: dict[str, Family], days: list[date], *, seed: int = 3) -> list[dict[str, str]]:
    """Shape one row per date, so a series can be measured rather than a single value."""
    rng = random.Random(seed)
    table_scale = scale()
    out = []
    for when in days:
        values = {name: "0" for name in columns}
        out.append(dict(shape_row(values, columns, when=when, shape=shape(), scale=table_scale, rng=rng)))
    return out


def mean_of(rows: list[dict[str, str]], column: str) -> float:
    return statistics.mean(float(row[column]) for row in rows)


# --- the window ----------------------------------------------------------------


def test_the_window_ends_today_by_default() -> None:
    """The whole point: generated data reaches the present without being asked to."""
    today = date(2026, 9, 20)
    start, end = resolve_window(today=today)
    assert end == today
    assert start == today - timedelta(days=DEFAULT_WINDOW_DAYS)


def test_an_explicit_window_is_honoured_exactly() -> None:
    assert resolve_window(date(2025, 3, 1), date(2025, 9, 1)) == (
        date(2025, 3, 1),
        date(2025, 9, 1),
    )


def test_a_backwards_window_is_refused() -> None:
    with pytest.raises(GenerationError):
        resolve_window(date(2026, 1, 1), date(2025, 1, 1))


# --- time shape ----------------------------------------------------------------


def test_saturday_outsells_midweek() -> None:
    """A retail dataset where a weekend looks like a Tuesday reads as broken."""
    columns = {"order_count": Family.COUNT}
    saturdays = [date(2025, 1, 4) + timedelta(days=7 * n) for n in range(40)]
    tuesdays = [date(2025, 1, 7) + timedelta(days=7 * n) for n in range(40)]

    assert all(d.weekday() == 5 for d in saturdays)
    assert mean_of(rows_for(columns, saturdays), "order_count") > mean_of(
        rows_for(columns, tuesdays), "order_count"
    )


def test_december_outsells_may() -> None:
    columns = {"order_count": Family.COUNT}
    december = [date(2025, 12, d) for d in range(1, 29)]
    may = [date(2025, 5, d) for d in range(1, 29)]

    assert mean_of(rows_for(columns, december), "order_count") > mean_of(
        rows_for(columns, may), "order_count"
    )


def test_the_series_trends_upward_across_the_window() -> None:
    """Same weekday and same month at both ends, so only the trend can explain a difference."""
    columns = {"order_count": Family.COUNT}
    early = [date(2024, 3, 2) + timedelta(days=7 * n) for n in range(8)]
    late = [date(2025, 3, 1) + timedelta(days=7 * n) for n in range(8)]

    assert mean_of(rows_for(columns, late), "order_count") > mean_of(rows_for(columns, early), "order_count")


def test_a_row_with_no_date_is_still_produced() -> None:
    """Dimension-style tables have no date and must not crash or come out empty."""
    values = {"headcount": "0", "amount": "0"}
    families = {"headcount": Family.COUNT, "amount": Family.CURRENCY}
    out = shape_row(values, families, when=None, shape=shape(), scale=scale(), rng=random.Random(1))
    assert float(out["headcount"]) > 0
    assert float(out["amount"]) > 0


# --- coherence -----------------------------------------------------------------


def test_an_amount_is_its_count_times_a_stable_price() -> None:
    """Two numbers on one dashboard must not contradict each other."""
    columns = {"order_count": Family.COUNT, "revenue": Family.CURRENCY}
    rows = rows_for(columns, [date(2025, 6, 1) + timedelta(days=n) for n in range(60)])

    per_unit = [float(r["revenue"]) / float(r["order_count"]) for r in rows]
    spread = statistics.pstdev(per_unit) / statistics.mean(per_unit)
    assert spread < 0.15, "unit price wanders, so revenue and order count tell different stories"


def test_cost_of_revenue_lines_stay_below_the_revenue_they_come_from() -> None:
    columns = {"revenue": Family.CURRENCY, "cogs": Family.CURRENCY, "opex": Family.CURRENCY}
    rows = rows_for(columns, [date(2025, 6, 1) + timedelta(days=n) for n in range(60)])

    for row in rows:
        revenue, cogs, opex = (float(row[c]) for c in ("revenue", "cogs", "opex"))
        assert 0 < cogs < revenue
        assert 0 < opex < revenue
        assert cogs + opex < revenue, "a P&L that never makes money is not plausible either"


def test_a_derived_average_is_the_ratio_of_its_inputs() -> None:
    columns = {
        "order_count": Family.COUNT,
        "revenue": Family.CURRENCY,
        "avg_order_value": Family.DERIVED,
    }
    rows = rows_for(columns, [date(2025, 6, 1) + timedelta(days=n) for n in range(40)])

    for row in rows:
        implied = float(row["revenue"]) / float(row["order_count"])
        assert abs(float(row["avg_order_value"]) - implied) / implied < 0.1


def test_scores_stay_on_the_scale_their_name_implies() -> None:
    rng = random.Random(5)
    families = {"nps_score": Family.SCORE, "avg_rating": Family.DERIVED}
    for _ in range(50):
        out = shape_row(
            {"nps_score": "0", "avg_rating": "0"},
            families,
            when=date(2025, 6, 1),
            shape=shape(),
            scale=scale(),
            rng=rng,
        )
        assert -100 <= float(out["nps_score"]) <= 100


def test_scores_do_not_follow_demand() -> None:
    """A busy Saturday does not make shoppers happier."""
    columns = {"nps_score": Family.SCORE}
    saturdays = [date(2025, 1, 4) + timedelta(days=7 * n) for n in range(40)]
    tuesdays = [date(2025, 1, 7) + timedelta(days=7 * n) for n in range(40)]

    busy = mean_of(rows_for(columns, saturdays), "nps_score")
    quiet = mean_of(rows_for(columns, tuesdays), "nps_score")
    assert abs(busy - quiet) / max(abs(quiet), 1.0) < 0.25


# --- type authority ------------------------------------------------------------


def test_an_integer_column_never_receives_a_decimal() -> None:
    """The rule FEAT-007 learned when a name pattern overrode a declared type.

    `hour_start` is an INTEGER whose name looks like something else, and writing a
    non-integer into it made the warehouse reject the load.
    """
    families = {"kwh": Family.UNITS, "some_rate": Family.RATIO, "spend": Family.CURRENCY}
    rng = random.Random(2)
    for _ in range(40):
        out = shape_row(
            {name: "0" for name in families},
            families,
            when=date(2025, 6, 1),
            shape=shape(),
            scale=scale(),
            rng=rng,
            integers=frozenset(families),
        )
        for value in out.values():
            int(value)  # raises if anything wrote a decimal into a declared integer


# --- classification ------------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("order_count", Family.COUNT),
        ("quantity", Family.COUNT),
        ("revenue", Family.CURRENCY),
        ("maintenance_cost", Family.CURRENCY),
        ("nps_score", Family.SCORE),
        ("sell_through_rate", Family.RATIO),
        ("avg_order_value", Family.DERIVED),
        ("revenue_per_sqft", Family.DERIVED),
        ("kwh", Family.UNITS),
        ("store_name", Family.OTHER),
    ],
)
def test_columns_are_classified_by_pattern(column: str, expected: Family) -> None:
    assert family_of(column) == expected
