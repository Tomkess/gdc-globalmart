"""The question and conversation script, and what it measures.

`config/questions.yaml` is three things at once, deliberately: the demo runbook, the routing
measurement input, and the regression set when a prompt changes. Loading it here means a
question added to the file is automatically part of every measurement, including FEAT-014's
protocol comparison — nobody has to remember to update a second list.

**`expect` is a human judgement, written before the prompts existed.** That ordering matters:
expectations derived from what the router already does measure nothing.

A router that returns *fewer* workspaces than expected has missed something. One that returns
*more* is broadcasting, which is the failure this whole exercise exists to avoid. Both count
as misses, and they are reported separately because they are different problems with
different fixes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_SCRIPT_PATH = Path("config/questions.yaml")


class ScriptError(Exception):
    """The script is missing or malformed."""


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    expect: tuple[str, ...]
    kind: str = ""
    shows: str = ""
    inject_failure: str | None = None
    enrich: bool = False


@dataclass(frozen=True)
class Conversation:
    id: str
    turns: tuple[Question, ...]
    shows: str = ""


@dataclass
class RouteOutcome:
    """How one question's routing compared to the human judgement."""

    question: Question
    chosen: tuple[str, ...]
    missed: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()
    error: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0

    def exact(self) -> bool:
        return not self.missed and not self.extra and self.error is None


@dataclass
class RouteReport:
    outcomes: list[RouteOutcome] = field(default_factory=list)

    def exact(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.exact())

    def summary_lines(self) -> list[str]:
        total = len(self.outcomes)
        if not total:
            return ["no questions"]
        broadcast = sum(1 for o in self.outcomes if o.extra and not o.missed)
        incomplete = sum(1 for o in self.outcomes if o.missed)
        failed = sum(1 for o in self.outcomes if o.error)
        lines = [
            f"questions         : {total}",
            f"exact             : {self.exact()}/{total}",
            f"over-routed       : {broadcast}   (called a workspace nothing needed)",
            f"under-routed      : {incomplete}   (missed a workspace the question needed)",
            f"failed            : {failed}",
            f"tokens            : {sum(o.tokens_in for o in self.outcomes):,} in / "
            f"{sum(o.tokens_out for o in self.outcomes):,} out",
        ]
        for outcome in self.outcomes:
            if outcome.exact():
                continue
            detail = outcome.error or ""
            if outcome.missed:
                detail += f" missed={','.join(outcome.missed)}"
            if outcome.extra:
                detail += f" extra={','.join(outcome.extra)}"
            lines.append(f"  {outcome.question.id}: {detail.strip()}")
        return lines


def _question(raw: dict[str, Any], *, index: int) -> Question:
    identifier = str(raw.get("id") or f"q{index}")
    text = str(raw.get("question") or "").strip()
    if not text:
        raise ScriptError(f"{identifier}: no question text")
    expect = tuple(str(item) for item in raw.get("expect") or ())
    if not expect:
        raise ScriptError(
            f"{identifier}: no `expect`. A question with no expected workspaces measures "
            "nothing — say what a competent analyst would consult."
        )
    return Question(
        id=identifier,
        question=text,
        expect=expect,
        kind=str(raw.get("kind") or ""),
        shows=" ".join(str(raw.get("shows") or "").split()),
        inject_failure=raw.get("inject_failure"),
        enrich=bool(raw.get("enrich")),
    )


def load_script(path: Path = DEFAULT_SCRIPT_PATH) -> tuple[tuple[Question, ...], tuple[Conversation, ...]]:
    path = Path(path)
    if not path.exists():
        raise ScriptError(f"No script at {path}")
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    questions = tuple(_question(item, index=index) for index, item in enumerate(raw.get("questions") or []))
    conversations = tuple(
        Conversation(
            id=str(item.get("id") or f"c{index}"),
            shows=" ".join(str(item.get("shows") or "").split()),
            turns=tuple(
                _question(turn, index=turn_index) for turn_index, turn in enumerate(item.get("turns") or [])
            ),
        )
        for index, item in enumerate(raw.get("conversations") or [])
    )

    if not questions and not conversations:
        raise ScriptError(f"{path} contains no questions")
    return questions, conversations


def compare(question: Question, chosen: tuple[str, ...]) -> RouteOutcome:
    expected = set(question.expect)
    got = set(chosen)
    return RouteOutcome(
        question=question,
        chosen=chosen,
        missed=tuple(sorted(expected - got)),
        extra=tuple(sorted(got - expected)),
    )
