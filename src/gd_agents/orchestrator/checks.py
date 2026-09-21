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


def _windows(answers: Sequence[Answer]) -> list[tuple[str, str, str]]:
    return [
        (a.workspace, a.shape.time_from or "", a.shape.time_to or "")
        for a in answers
        if a.shape.time_from or a.shape.time_to
    ]


def _time_window_match(answers: Sequence[Answer]) -> Result:
    known = _windows(answers)
    if len(known) < 2:
        return Result("time_window_match", Verdict.UNKNOWN, "fewer than two lanes reported a window")
    distinct = {(start, end) for _, start, end in known}
    if len(distinct) > 1:
        listed = "; ".join(f"{ws} {start}..{end}" for ws, start, end in known)
        return Result(
            "time_window_match",
            Verdict.FAIL,
            f"windows differ ({listed}). A comparison across different periods is invalid "
            "however natural it reads.",
        )
    return Result("time_window_match", Verdict.PASS, "same window")


def _shared_dimension(answers: Sequence[Answer]) -> Result:
    # Count the lanes that *reported*, not the distinct values. Two lanes both saying
    # "month" is agreement — the strongest possible pass — and counting distinct values
    # made it indistinguishable from nobody having said anything.
    reported = [a.shape.grain for a in answers if a.shape.grain]
    if len(reported) < 2:
        return Result("shared_dimension", Verdict.UNKNOWN, "fewer than two lanes reported a grain")
    grains = set(reported)
    if len(grains) > 1:
        return Result(
            "shared_dimension",
            Verdict.FAIL,
            f"no common key: grains are {', '.join(sorted(grains))}. Report separately rather "
            "than asserting a relationship.",
        )
    return Result("shared_dimension", Verdict.PASS, f"common grain {next(iter(grains))}")


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


def check_provenance(merged: str, answers: Sequence[Answer]) -> Provenance:
    """Every number in the merged answer must appear in some lane's result.

    Separators are normalised before comparing, so "11,944.45" and "11944.45" are the same
    number written two ways rather than one invented and one real. Years are already excluded
    upstream: treating them as provenance would licence any value between 1900 and 2200.
    """

    def normalise(value: str) -> str:
        return value.replace(",", "").replace(" ", "").rstrip("%").rstrip(".")

    known = {normalise(number) for answer in answers for number in answer.numbers}
    result = Provenance(known=len(known))

    invented: list[str] = []
    for match in _NUMBER.finditer(merged or ""):
        raw = match.group(0).strip()
        bare = normalise(raw)
        if not bare or bare.lstrip("-").replace(".", "").isdigit() is False:
            continue
        digits = bare.lstrip("-")
        if digits.isdigit() and len(digits) == 4 and 1900 <= int(digits) <= 2200:
            continue
        result.checked += 1
        if bare not in known:
            invented.append(raw)

    result.invented = tuple(dict.fromkeys(invented))
    return result
