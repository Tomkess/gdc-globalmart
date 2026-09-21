"""Whether two answers may be combined, and what the merge is forbidden to do.

Two answers computed against different data models are not automatically combinable, and a
merge that invents a link is worse than one that declines. Infobip's own Overview workspace
was their attempt at combining everything and it was not sufficient — so a fabricated
connection is precisely the failure mode this audience already recognises.

**A registry, not a prompt.** Each check has an id, what it guards against, and whether code
or the model decides it. Adding a ninth is an entry in `CHECKS`; nothing else changes. The
eight here are a starting set and the file says so — completeness is not claimed.

**Six are decided in code and gate the merge.** Two are judgement and are posed to the model
as structured verdicts rather than left implicit in prose, because "is this the same metric"
cannot be answered by comparing strings across four independent models.

**The hard rule is `numeric_provenance`.** The merge may compare, rank, sequence and
narrate, but every number in its output must appear in some lane's result. No sums across
workspaces, no ratios spanning two sources. "Cost per NPS point" — marketing spend divided
by a customer-workspace score — is the archetype: both numbers real, the quotient
meaningless, because the grains and populations differ. That rule is checked after the fact
rather than requested in a prompt, which is the only version of it that holds.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from gd_agents.lane import Answer


class Decider(StrEnum):
    CODE = "code"
    MODEL = "model"


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "n/a"
    UNKNOWN = "unknown"
    """The check could not be decided — usually because a lane did not report its shape.
    Distinct from PASS on purpose: a check cannot pass on an absence it never established."""


@dataclass(frozen=True)
class Result:
    check: str
    verdict: Verdict
    reason: str = ""

    def blocks(self) -> bool:
        return self.verdict is Verdict.FAIL


@dataclass(frozen=True)
class Check:
    """One reason two answers might not combine."""

    id: str
    guards_against: str
    decided_by: Decider
    run: Callable[[Sequence[Answer]], Result] | None = None
    """Absent for a `MODEL` check — those are posed in the merge prompt instead."""


# --- the deterministic six ----------------------------------------------------


def _lane_completeness(answers: Sequence[Answer]) -> Result:
    failed = [a.workspace for a in answers if not a.ok()]
    empty = [a.workspace for a in answers if a.ok() and not a.shape.returned_data]
    if failed or empty:
        detail = []
        if failed:
            detail.append(f"failed: {', '.join(failed)}")
        if empty:
            detail.append(f"returned no data: {', '.join(empty)}")
        return Result(
            "lane_completeness",
            Verdict.FAIL,
            "; ".join(detail) + ". Synthesise only from what answered, and say what did not.",
        )
    return Result("lane_completeness", Verdict.PASS, "every lane answered with data")


def _windows_of(answer: Answer) -> set[str]:
    """Every period the lane covered, as it expressed them.

    `time_from` and `time_to` are one window's two ends, so they collapse to a single
    string. Reading them as two separate values would let a lane covering April–September
    "share" a window with one covering April–June, on the strength of the start date alone.
    """
    if answer.shape.windows:
        return set(answer.shape.windows)
    if answer.shape.time_from or answer.shape.time_to:
        return {f"{answer.shape.time_from or '?'}..{answer.shape.time_to or '?'}"}
    return set()


def _grains_of(answer: Answer) -> set[str]:
    """Every breakdown the lane returned."""
    if answer.shape.grains:
        return set(answer.shape.grains)
    return {answer.shape.grain} if answer.shape.grain else set()


def _overlap(
    check: str,
    answers: Sequence[Answer],
    of: Callable[[Answer], set[str]],
    *,
    noun: str,
    on_fail: str,
) -> Result:
    """Pass when every reporting lane shares at least one value; fail when none is common.

    An overlap rather than equality, because a lane can legitimately return more than one
    chart. A sub-question may ask a workspace for a ranking *and* a monthly series, and a
    lane holding {campaign_id, month} against one holding {month} does share a key — month.
    Requiring a single value made the extra chart a reason to refuse, which punished the
    lane for answering the question more fully than the minimum.

    What it will not do is manufacture agreement: with nothing in common it still fails, and
    with fewer than two lanes reporting it returns UNKNOWN rather than passing on an absence.
    """
    reported = [(a.workspace, of(a)) for a in answers if of(a)]
    if len(reported) < 2:
        return Result(check, Verdict.UNKNOWN, f"fewer than two lanes reported a {noun}")

    common = set.intersection(*(values for _, values in reported))
    if not common:
        listed = "; ".join(f"{ws} {', '.join(sorted(values))}" for ws, values in reported)
        return Result(check, Verdict.FAIL, f"{on_fail} ({listed})")

    agreed = ", ".join(sorted(common))
    extra = [
        f"{ws} also returned {', '.join(sorted(values - common))}"
        for ws, values in reported
        if values - common
    ]
    reason = f"common {noun} {agreed}"
    if extra:
        # Said out loud, because the merge is about to be handed material the lanes do not
        # both hold, and a reader should know which part of it is comparable.
        reason += " (" + "; ".join(extra) + ")"
    return Result(check, Verdict.PASS, reason)


def _time_window_match(answers: Sequence[Answer]) -> Result:
    return _overlap(
        "time_window_match",
        answers,
        _windows_of,
        noun="window",
        on_fail=(
            "no shared period. A comparison across different periods is invalid however "
            "natural it reads"
        ),
    )


def _shared_dimension(answers: Sequence[Answer]) -> Result:
    return _overlap(
        "shared_dimension",
        answers,
        _grains_of,
        noun="grain",
        on_fail="no common key. Report separately rather than asserting a relationship",
    )


def _filter_parity(answers: Sequence[Answer]) -> Result:
    reported = [(a.workspace, frozenset(a.shape.filters)) for a in answers if a.shape.filters]
    if not reported:
        return Result("filter_parity", Verdict.NOT_APPLICABLE, "no lane reported a filter")
    if len({filters for _, filters in reported}) > 1 or len(reported) != len(answers):
        listed = "; ".join(f"{ws}: {', '.join(sorted(f)) or 'none'}" for ws, f in reported)
        return Result(
            "filter_parity",
            Verdict.FAIL,
            f"filters differ ({listed}), which implies a comparability that does not exist.",
        )
    return Result("filter_parity", Verdict.PASS, "same filters")


def _unit_compatibility(answers: Sequence[Answer]) -> Result:
    reported = [a.shape.units for a in answers if a.shape.units]
    if len(reported) < 2:
        return Result("unit_compatibility", Verdict.UNKNOWN, "fewer than two lanes reported units")
    units = set(reported)
    if len(units) > 1:
        return Result(
            "unit_compatibility",
            Verdict.FAIL,
            f"mixed units ({', '.join(sorted(units))}); they cannot be added or compared directly.",
        )
    return Result("unit_compatibility", Verdict.PASS, f"all {next(iter(units))}")


CHECKS: tuple[Check, ...] = (
    Check(
        "lane_completeness",
        "synthesising as if a failed lane had answered",
        Decider.CODE,
        _lane_completeness,
    ),
    Check(
        "time_window_match",
        "comparing last quarter against last month",
        Decider.CODE,
        _time_window_match,
    ),
    Check(
        "shared_dimension",
        "claiming a link with no common key at the same grain",
        Decider.CODE,
        _shared_dimension,
    ),
    Check(
        "filter_parity",
        "one lane filtered to a region, the other not",
        Decider.CODE,
        _filter_parity,
    ),
    Check(
        "unit_compatibility",
        "mixing currencies or units",
        Decider.CODE,
        _unit_compatibility,
    ),
    Check(
        "numeric_provenance",
        "any number in the output that no lane produced",
        Decider.CODE,
        None,  # checked against the merged text, so it runs after the merge, not before
    ),
    Check(
        "metric_identity",
        "assuming the same word means the same metric across models",
        Decider.MODEL,
    ),
    Check(
        "population_parity",
        'comparing "customers who bought" against "all customers"',
        Decider.MODEL,
    ),
)


@dataclass
class CheckReport:
    results: tuple[Result, ...] = ()

    def blocking(self) -> tuple[Result, ...]:
        return tuple(result for result in self.results if result.blocks())

    def combinable(self) -> bool:
        return not self.blocking()

    def reasons(self) -> str:
        """Why the answers cannot be combined, for the reader rather than the log."""
        return " ".join(result.reason for result in self.blocking())

    def summary_lines(self) -> list[str]:
        return [f"  {r.check:20} {r.verdict.value:8} {r.reason}" for r in self.results]


def run_checks(answers: Sequence[Answer]) -> CheckReport:
    """Every deterministic check, in registry order. Judgement checks are not run here."""
    if len(answers) < 2:
        return CheckReport(
            results=(Result("shared_dimension", Verdict.NOT_APPLICABLE, "single lane, nothing to combine"),)
        )
    return CheckReport(results=tuple(check.run(answers) for check in CHECKS if check.run is not None))


def model_check_prompt() -> str:
    """The judgement checks, as the merge prompt must pose them."""
    lines = [f"- {check.id}: {check.guards_against}" for check in CHECKS if check.decided_by is Decider.MODEL]
    return "\n".join(lines)


# --- numeric provenance: the hard rule ----------------------------------------

#: Same shape the lane uses, so what is extracted from a merged answer is comparable with
#: what was extracted from each lane's result.
_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?%?(?![\w])")


@dataclass
class Provenance:
    invented: tuple[str, ...] = ()
    checked: int = 0
    known: int = 0
    notes: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.invented

    def as_result(self) -> Result:
        if self.ok():
            return Result(
                "numeric_provenance",
                Verdict.PASS,
                f"all {self.checked} number(s) in the answer came from a lane",
            )
        return Result(
            "numeric_provenance",
            Verdict.FAIL,
            f"invented: {', '.join(self.invented[:6])}. The merge may compare and narrate, "
            "never compute — a value in neither lane is a value nobody measured.",
        )


def _as_number(value: str) -> float | None:
    """The numeric value of a rendered number, or None if it is not one."""
    bare = value.replace(",", "").replace(" ", "").rstrip("%").rstrip(".")
    try:
        return float(bare)
    except ValueError:
        return None


def check_provenance(merged: str, answers: Sequence[Answer]) -> Provenance:
    """Every number in the merged answer must appear in some lane's result.

    **Compared numerically, not textually.** A lane returning `3,995.00` and a merge writing
    `3,995` are the same number written two ways — the first version of this check compared
    normalised strings and flagged that as invented, which would have rejected a perfectly
    honest single-lane answer. Found by running it against a real question.

    Numeric comparison keeps the teeth: 441.73 is not equal to 11944.45 or 27.04, so the
    archetype — a ratio spanning two workspaces — is still caught. So is a merge that rounds
    11,944.45 to 11,944, which is a changed value however innocuous it looks.

    Years are excluded. Treating them as provenance would licence any value between 1900 and
    2200.
    """
    known: set[float] = set()
    literals: set[str] = set()
    for answer in answers:
        for number in answer.numbers:
            literals.add(number)
            value = _as_number(number)
            if value is not None:
                known.add(value)

    result = Provenance(known=len(known))

    invented: list[str] = []
    for match in _NUMBER.finditer(merged or ""):
        raw = match.group(0).strip()
        value = _as_number(raw)
        if value is None:
            continue
        if value.is_integer() and 1900 <= value <= 2200 and "." not in raw:
            continue
        result.checked += 1
        if value not in known and raw not in literals:
            invented.append(raw)

    result.invented = tuple(dict.fromkeys(invented))
    return result
