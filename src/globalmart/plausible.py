"""Makes generated numbers behave like retail instead of like noise.

FEAT-007 generated each column independently and uniformly, which is correct for
referential integrity and wrong for anything a person looks at. A revenue line was flat
noise, a weekend was indistinguishable from a Tuesday, and margin had no relationship to
the revenue and cost sitting beside it in the same row.

That was a deliberate deferral — *"inventing plausible retail data with no consumer able to
judge it is how a dataset quietly becomes worse while every test still passes."* The
objection held while no judge existed. GlobalMart now faces prospects, so one does.

**The scope is what a dashboard renders.** Measured across all 13 workspaces: 1,025 metrics
resolve to 125 distinct fact columns over 75 tables, of which 42 have more than one rendered
column. Those 42 collapse into four repeating shapes, which is what this module implements.
Anything no visualization draws is deliberately untouched.

**No table and no column is named here.** The same property `plan_columns` has, for the same
reason: a table added to the DDL gets plausible values without an edit to this file.

Two things are modelled:

*Time.* Every dated row carries an intensity taken from its own date — a gentle trend, an
annual season peaking in the run-up to December, and a day-of-week effect. A Saturday
outsells a Tuesday because in retail it does.

*Coherence within a row.* An amount beside a count is that count times a price. A cost
beside a quantity is that quantity times a rate. A margin is computed from the revenue it
sits next to, never drawn on its own. Two numbers on one dashboard cannot contradict each
other if one is derived from the other.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

#: Retail weekly rhythm, normalised to average 1.0 so the shape changes but the volume does
#: not. Monday is index 0. Saturday carries the week; midweek is the trough.
WEEKDAY_FACTORS = (0.84, 0.81, 0.87, 0.96, 1.18, 1.44, 1.10)

#: Day of the year the annual season peaks — early December, ahead of the holiday.
SEASON_PEAK_DAY = 340

#: How much the season swings either side of the mean. 0.28 gives a visible but not absurd
#: December against a February.
SEASON_AMPLITUDE = 0.28

#: Total growth across the whole window. Enough to read as a trend on a chart without
#: turning every series into a hockey stick.
TREND_TOTAL = 0.32

#: How far an individual row strays from its date's intensity. Without this every row on a
#: day is identical, which looks as synthetic as pure noise does.
ROW_JITTER = 0.22


class Family(StrEnum):
    """What a numeric column means, inferred from its name."""

    COUNT = "count"
    CURRENCY = "currency"
    UNITS = "units"
    SCORE = "score"
    RATIO = "ratio"
    DERIVED = "derived"
    OTHER = "other"


#: Name patterns per family. Order matters: the first family whose pattern matches wins, so
#: the more specific families are tested first.
_PATTERNS: tuple[tuple[Family, tuple[str, ...]], ...] = (
    (Family.DERIVED, ("avg_", "_per_", "average_")),
    (Family.RATIO, ("_rate", "_ratio", "_pct", "_percent", "_share", "_quartile")),
    (Family.SCORE, ("_score", "_rating", "score", "rating")),
    (Family.COUNT, ("_count", "count", "_qty", "quantity", "_units", "units", "headcount")),
    (
        Family.CURRENCY,
        (
            "amount",
            "revenue",
            "cost",
            "cogs",
            "opex",
            "spend",
            "price",
            "value",
            "budget",
            "pay",
            "bonus",
            "discount",
            "margin",
            "ebitda",
            "recharge",
        ),
    ),
    (Family.UNITS, ("points", "kwh", "tons", "hours", "sqft", "days")),
)

#: Cost lines that are a fraction of the revenue in the same row, with the fraction each
#: one plausibly takes. A margin that is drawn independently is the single most visible
#: way for a P&L dashboard to look wrong.
_COST_OF_REVENUE: tuple[tuple[str, tuple[float, float]], ...] = (
    ("cogs", (0.54, 0.67)),
    ("opex", (0.16, 0.26)),
    ("margin", (0.28, 0.42)),
    ("ebitda", (0.08, 0.19)),
)

_REVENUE_HINTS = ("revenue", "sales_amount", "gross_revenue")


def family_of(column: str) -> Family:
    """Classify one column name. Pure pattern matching — no column is named."""
    lowered = column.lower()
    for family, patterns in _PATTERNS:
        if any(pattern in lowered for pattern in patterns):
            return family
    return Family.OTHER


@dataclass(frozen=True)
class TimeShape:
    """Turns a date into a demand intensity.

    Three independent effects multiplied together, each of which a viewer recognises on sight:
    a trend across the window, an annual season, and the weekly rhythm.
    """

    start: date
    end: date
    trend_total: float = TREND_TOTAL
    season_amplitude: float = SEASON_AMPLITUDE
    peak_day: int = SEASON_PEAK_DAY

    def trend(self, when: date) -> float:
        span = max((self.end - self.start).days, 1)
        progress = min(max((when - self.start).days / span, 0.0), 1.0)
        return 1.0 + self.trend_total * progress

    def season(self, when: date) -> float:
        offset = (when.timetuple().tm_yday - self.peak_day) / 365.0
        return 1.0 + self.season_amplitude * math.cos(2 * math.pi * offset)

    def weekday(self, when: date) -> float:
        return WEEKDAY_FACTORS[when.weekday()]

    def intensity(self, when: date) -> float:
        """The combined multiplier for one date. Never returns zero or negative."""
        value = self.trend(when) * self.season(when) * self.weekday(when)
        return max(value, 0.05)


def jitter(rng: random.Random, amount: float = ROW_JITTER) -> float:
    """A small multiplicative wobble, so rows on one day are not identical."""
    return max(1.0 + rng.uniform(-amount, amount), 0.05)


@dataclass(frozen=True)
class TableScale:
    """One table's own sense of size, drawn once and reused for every row.

    Two tables that both hold a count should not both hover around 500. Drawing a base and
    a unit price per table is what gives a ranked chart a shape and makes one fact table
    visibly bigger business than another.
    """

    base_count: float
    unit_price: float
    unit_rate: float

    @classmethod
    def draw(cls, rng: random.Random) -> TableScale:
        return cls(
            base_count=rng.uniform(4.0, 180.0),
            unit_price=round(rng.uniform(6.0, 240.0), 2),
            unit_rate=round(rng.uniform(0.4, 38.0), 2),
        )


def shape_row(
    values: dict[str, str],
    families: dict[str, Family],
    *,
    when: date | None,
    shape: TimeShape,
    scale: TableScale,
    rng: random.Random,
    integers: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Rewrite one row's numeric columns so they are coherent and time-shaped.

    Applied after the structural pass, so keys, foreign keys, dates and text are already
    settled and are never touched here. Returns the row; mutates in place for the caller's
    convenience.

    ``integers`` names the columns the DDL declares as integral. **The declared type wins**,
    always — a column being conceptually a rate does not license writing `255.87` into an
    INTEGER. That rule was learned once already, when a name pattern overrode a type and the
    warehouse rejected the load.

    The four shapes, in the order they are resolved:

    1. **counts** take the date's intensity times the table's base size.
    2. **units** behave like counts but on their own rate.
    3. **currency** derives from a count or unit in the same row when there is one, so an
       amount is always some quantity times a price. With nothing to derive from it falls
       back to the intensity directly.
    4. **derived and cost-of-revenue** columns are computed from the row's revenue rather
       than drawn, which is what keeps a margin bridge internally consistent.

    Scores and ratios are deliberately independent of volume: a busy Saturday does not make
    shoppers happier.
    """
    intensity = shape.intensity(when) if when else 1.0

    counts: dict[str, float] = {}
    units: dict[str, float] = {}

    for column, family in families.items():
        if column not in values:
            continue
        if family is Family.COUNT:
            raw = scale.base_count * intensity * jitter(rng)
            counts[column] = max(round(raw), 1)
            values[column] = _fmt(column, counts[column], integers)
        elif family is Family.UNITS:
            raw = scale.base_count * intensity * jitter(rng) * rng.uniform(0.5, 3.0)
            units[column] = round(raw, 2)
            values[column] = _fmt(column, units[column], integers)
        elif family is Family.SCORE:
            values[column] = _fmt(column, _score(column, rng), integers)
        elif family is Family.RATIO:
            values[column] = _fmt(column, _ratio(column, rng), integers)

    driver = next(iter(counts.values()), None)
    unit_driver = next(iter(units.values()), None)

    revenue: float | None = None
    for column, family in families.items():
        if family is not Family.CURRENCY or column not in values:
            continue
        if driver is not None:
            amount = driver * scale.unit_price * jitter(rng, 0.10)
        elif unit_driver is not None:
            amount = unit_driver * scale.unit_rate * jitter(rng, 0.10)
        else:
            amount = scale.base_count * scale.unit_price * intensity * jitter(rng)
        values[column] = _fmt(column, amount, integers)
        if revenue is None and any(hint in column.lower() for hint in _REVENUE_HINTS):
            revenue = amount

    if revenue is None:
        revenue = next(
            (float(values[c]) for c, f in families.items() if f is Family.CURRENCY and c in values),
            None,
        )

    if revenue is not None:
        for column, family in families.items():
            if family is not Family.CURRENCY or column not in values:
                continue
            lowered = column.lower()
            for hint, (low, high) in _COST_OF_REVENUE:
                if hint in lowered and not any(r in lowered for r in _REVENUE_HINTS):
                    values[column] = _fmt(column, revenue * rng.uniform(low, high), integers)
                    break

    for column, family in families.items():
        if family is not Family.DERIVED or column not in values:
            continue
        values[column] = _fmt(column, _derive(column, revenue, driver, unit_driver, scale, rng), integers)

    return values


def _fmt(column: str, value: float | str, integers: frozenset[str]) -> str:
    """Render one number as the DDL says it must be stored."""
    number = float(value)
    if column in integers:
        return str(int(round(number)))
    return f"{number:.2f}"


def _score(column: str, rng: random.Random) -> float:
    """Scores live on the scale their name implies, not on an arbitrary one."""
    lowered = column.lower()
    if "nps" in lowered:
        return float(rng.randint(-20, 90))
    if "rating" in lowered:
        return round(rng.uniform(3.1, 4.9), 1)
    if "sentiment" in lowered:
        return round(rng.uniform(-0.4, 0.85), 2)
    return round(rng.uniform(58.0, 98.0), 1)


def _ratio(column: str, rng: random.Random) -> float:
    lowered = column.lower()
    if "quartile" in lowered:
        return float(rng.randint(1, 4))
    if any(hint in lowered for hint in ("_pct", "_percent")):
        return round(rng.uniform(1.5, 88.0), 1)
    return round(rng.uniform(0.04, 0.72), 3)


def _derive(
    column: str,
    revenue: float | None,
    driver: float | None,
    unit_driver: float | None,
    scale: TableScale,
    rng: random.Random,
) -> float:
    """An average or a per-something is computed, never drawn.

    `avg_order_value` beside a revenue and an order count must be the one divided by the
    other, or the dashboard shows three numbers that disagree.
    """
    if revenue is not None and driver:
        return revenue / max(driver, 1) * jitter(rng, 0.05)
    if revenue is not None and unit_driver:
        return revenue / max(unit_driver, 1.0) * jitter(rng, 0.05)
    return scale.unit_price * jitter(rng, 0.15)
