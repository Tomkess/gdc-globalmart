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
    """One scripted question. Every entry carries the same keys, in the same order.

    `id`, `question` and `expect` are required — a question with no expected workspaces
    measures nothing. `kind` groups it, `shows` says what a reader should watch for, and
    `note` records a decision about the entry itself, most often why an expectation was
    changed. `note` is read rather than ignored: a key the loader silently drops is debris
    the next person has to guess about.
    """

    id: str
    question: str
    expect: tuple[str, ...]
    kind: str = ""
    shows: str = ""
    note: str = ""
    inject_failure: str | None = None
    enrich: bool = False
    reply_to: str | None = None
    """A turn that answers a workspace's `input-required` question rather than asking a new
    one. Named, because the reply goes to that lane alone on its own conversation."""

    from_memory: bool = False
    """A turn that needs no workspace at all — "summarise what we have established" asks
    about the conversation, and the conversation is already held. Routing nowhere is the
    right answer, so `expect` is empty and an empty route scores as exact."""


@dataclass(frozen=True)
class Conversation:
    id: str
    turns: tuple[Question, ...]
    kind: str = ""
    shows: str = ""
    note: str = ""


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


#: Everything an entry may carry. An unknown key is a typo or a convention someone invented
#: locally, and either way it is better refused at load than ignored until it matters.
QUESTION_KEYS = frozenset(
    {
        "id",
        "question",
        "expect",
        "kind",
        "shows",
        "note",
        "inject_failure",
        "enrich",
        "reply_to",
        "from_memory",
    }
)
CONVERSATION_KEYS = frozenset({"id", "kind", "shows", "note", "turns"})


def _question(raw: dict[str, Any], *, index: int, where: str = "") -> Question:
    # Parenthesised deliberately: without them Python reads this as
    # `(raw.get("id") or fallback) if where else f"q{index}"`, which throws away the id of
    # every top-level question and labels them q0, q1, q2 in every report.
    fallback = f"{where}turn-{index + 1}" if where else f"q{index}"
    identifier = str(raw.get("id") or fallback)
    unknown = set(raw) - QUESTION_KEYS
    if unknown:
        raise ScriptError(
            f"{identifier}: unknown key(s) {', '.join(sorted(unknown))}. "
            f"An entry may carry: {', '.join(sorted(QUESTION_KEYS))}."
        )
    text = " ".join(str(raw.get("question") or "").split())
    if not text:
        raise ScriptError(f"{identifier}: no question text")
    from_memory = bool(raw.get("from_memory"))
    expect = tuple(str(item) for item in raw.get("expect") or ())
    if expect and from_memory:
        raise ScriptError(
            f"{identifier}: `from_memory` means no workspace is called, so `expect` must be empty."
        )
    if not expect and not from_memory:
        raise ScriptError(
            f"{identifier}: no `expect`. A question with no expected workspaces measures "
            "nothing — say what a competent analyst would consult, or set `from_memory: true` "
            "if the turn is answerable from the conversation alone."
        )
    return Question(
        id=identifier,
        question=text,
        expect=expect,
        kind=str(raw.get("kind") or ""),
        shows=" ".join(str(raw.get("shows") or "").split()),
        note=" ".join(str(raw.get("note") or "").split()),
        inject_failure=raw.get("inject_failure"),
        enrich=bool(raw.get("enrich")),
        reply_to=raw.get("reply_to"),
        from_memory=from_memory,
    )


def load_script(path: Path = DEFAULT_SCRIPT_PATH) -> tuple[tuple[Question, ...], tuple[Conversation, ...]]:
    path = Path(path)
    if not path.exists():
        raise ScriptError(f"No script at {path}")
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    questions = tuple(_question(item, index=index) for index, item in enumerate(raw.get("questions") or []))

    conversations = []
    for index, item in enumerate(raw.get("conversations") or []):
        identifier = str(item.get("id") or f"c{index}")
        unknown = set(item) - CONVERSATION_KEYS
        if unknown:
            raise ScriptError(
                f"{identifier}: unknown key(s) {', '.join(sorted(unknown))}. "
                f"A conversation may carry: {', '.join(sorted(CONVERSATION_KEYS))}."
            )
        turns = tuple(
            _question(turn, index=turn_index, where=f"{identifier} ")
            for turn_index, turn in enumerate(item.get("turns") or [])
        )
        if not turns:
            raise ScriptError(f"{identifier}: a conversation with no turns")
        conversations.append(
            Conversation(
                id=identifier,
                kind=str(item.get("kind") or ""),
                shows=" ".join(str(item.get("shows") or "").split()),
                note=" ".join(str(item.get("note") or "").split()),
                turns=turns,
            )
        )

    if not questions and not conversations:
        raise ScriptError(f"{path} contains no questions")

    seen: set[str] = set()
    for identifier in [q.id for q in questions] + [c.id for c in conversations]:
        if identifier in seen:
            raise ScriptError(f"{identifier}: used twice. Ids name a result, so they must be unique.")
        seen.add(identifier)

    return questions, tuple(conversations)


def compare(question: Question, chosen: tuple[str, ...]) -> RouteOutcome:
    expected = set(question.expect)
    got = set(chosen)
    return RouteOutcome(
        question=question,
        chosen=chosen,
        missed=tuple(sorted(expected - got)),
        extra=tuple(sorted(got - expected)),
    )
