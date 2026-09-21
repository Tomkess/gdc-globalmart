"""Answer-level validation: does the published corpus actually answer the question?

FEAT-008 ended with an honest open item — "whether the assistant actually *retrieves* these
items well… cannot be settled by building more, only by asking it a question only the
document answers". This is that question, asked in a way that can run in CI.

**It asks the retrieval layer, not the assistant.** `GET /knowledge/search` runs the same
semantic search over the same chunks the assistant's knowledge skill uses, and returns the
matching chunks with their scores and filenames. Asserting there instead of on generated
prose is better in every way that matters: it is deterministic for a fixed index, it needs no
model, it cannot be flaky, and a failure names the chunk that was or was not retrieved rather
than an opinion about a paragraph. Whether the assistant then *words* the answer well is a
question for a human, and it stays one.

Two assertions per question, both necessary:

1. the expected document is in the results, within ``limit``;
2. the retrieved chunks contain the expected facts.

The first alone passes when the right document is found for the wrong reason. The second
alone passes when some other document happens to contain the sentence.

**The question set cannot rot silently.** ``assert_questions_grounded`` runs offline inside
``knowledge-docs build``: every ``expect_facts`` string must appear verbatim in the document
it names, and that document must carry ``anchor: true``. So an author who rewrites a
load-bearing sentence fails locally, by question id, in a check that needs no host — rather
than degrading a live suite nobody is watching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from globalmart.config import GlobalmartError
from globalmart.corpus import DEFAULT_QUESTIONS, CorpusDocument
from globalmart.knowledge_docs import DEFAULT_SEARCH_LIMIT, KnowledgeApi, SearchResult

_QUESTION_KEYS = frozenset({"id", "question", "expect_document", "expect_facts", "min_facts"})
_TOP_LEVEL_KEYS = frozenset({"version", "questions"})


class RetrievalError(GlobalmartError):
    """The question set is malformed, or is no longer grounded in the corpus."""


@dataclass(frozen=True)
class RetrievalQuestion:
    id: str
    question: str
    expect_document: str
    expect_facts: tuple[str, ...]
    #: How many of ``expect_facts`` must appear. Defaults to all of them.
    min_facts: int = 0

    @property
    def required_facts(self) -> int:
        return self.min_facts or len(self.expect_facts)


@dataclass
class RetrievalOutcome:
    question_id: str
    document_found: bool
    rank: int | None
    top_score: float | None
    matched_facts: tuple[str, ...]
    missing_facts: tuple[str, ...]
    required_facts: int
    returned: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.document_found and len(self.matched_facts) >= self.required_facts

    def line(self) -> str:
        mark = "ok     " if self.passed else "FAILED "
        rank = "-" if self.rank is None else f"#{self.rank}"
        score = "-" if self.top_score is None else f"{self.top_score:.3f}"
        return (
            f"{mark} {self.question_id:36s} rank={rank:4s} score={score:6s} "
            f"facts={len(self.matched_facts)}/{self.required_facts}"
        )


@dataclass
class RetrievalReport:
    target: str = ""
    workspace_id: str = ""
    limit: int = DEFAULT_SEARCH_LIMIT
    min_score: float = 0.0
    outcomes: list[RetrievalOutcome] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(outcome.passed for outcome in self.outcomes)

    @property
    def failures(self) -> tuple[RetrievalOutcome, ...]:
        return tuple(outcome for outcome in self.outcomes if not outcome.passed)

    def summary_lines(self) -> list[str]:
        lines = [
            f"target            : {self.target}",
            f"workspace         : {self.workspace_id}",
            f"questions         : {len(self.outcomes)}",
            f"passed            : {len(self.outcomes) - len(self.failures)}",
            f"search limit      : {self.limit}   min score: {self.min_score}",
            "",
        ]
        lines.extend(outcome.line() for outcome in self.outcomes)
        for outcome in self.failures:
            if not outcome.document_found:
                lines.append(
                    f"  {outcome.question_id}: expected document not in the top {self.limit} "
                    f"— returned {', '.join(outcome.returned) or '(nothing)'}"
                )
            if outcome.missing_facts:
                lines.append(
                    f"  {outcome.question_id}: facts not in the retrieved chunks: "
                    + "; ".join(repr(fact) for fact in outcome.missing_facts)
                )
        return lines


# --- text matching ------------------------------------------------------------


def normalise(text: str) -> str:
    """Casefold and collapse whitespace.

    Enough to survive reflowing a paragraph or changing its capitalisation, and not enough to
    survive a rewrite — which is the right sensitivity. A fact assertion that tolerated
    paraphrase would tolerate the fact changing meaning.
    """
    return re.sub(r"\s+", " ", text).strip().casefold()


def contains_fact(haystack: str, fact: str) -> bool:
    return normalise(fact) in normalise(haystack)


# --- the question set ---------------------------------------------------------


def load_questions(path: Path = DEFAULT_QUESTIONS) -> list[RetrievalQuestion]:
    """Strict loader. A missing file yields no questions rather than an error."""
    path = Path(path)
    if not path.exists():
        return []

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise RetrievalError(f"{path}: the question set must be a mapping")

    unknown = sorted(set(raw) - _TOP_LEVEL_KEYS)
    if unknown:
        raise RetrievalError(
            f"{path}: unknown key(s) {', '.join(repr(k) for k in unknown)}. "
            f"Allowed: {', '.join(sorted(_TOP_LEVEL_KEYS))}."
        )

    entries = raw.get("questions") or []
    if not isinstance(entries, list):
        raise RetrievalError(f"{path}: questions: must be a list")

    questions: list[RetrievalQuestion] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        where = f"{path}: questions[{index}]"
        if not isinstance(entry, dict):
            raise RetrievalError(f"{where}: must be a mapping")
        unknown_keys = sorted(set(entry) - _QUESTION_KEYS)
        if unknown_keys:
            raise RetrievalError(
                f"{where}: unknown key(s) {', '.join(repr(k) for k in unknown_keys)}. "
                f"Allowed: {', '.join(sorted(_QUESTION_KEYS))}."
            )

        def required(key: str, node: dict[str, Any] = entry, at: str = where) -> str:
            value = node.get(key)
            if not isinstance(value, str) or not value.strip():
                raise RetrievalError(f"{at}: {key!r} is required and must be a non-empty string")
            return value.strip()

        identifier = required("id")
        if identifier in seen:
            raise RetrievalError(f"{where}: duplicate question id {identifier!r}")
        seen.add(identifier)

        facts = entry.get("expect_facts") or []
        if isinstance(facts, str) or not facts:
            raise RetrievalError(
                f"{where}: expect_facts must be a non-empty list. A question with no expected "
                "fact asserts only that some document came back, which is not a test."
            )

        min_facts = int(entry.get("min_facts", 0) or 0)
        if min_facts < 0 or min_facts > len(facts):
            raise RetrievalError(
                f"{where}: min_facts must be between 0 and {len(facts)} (0 means all of them)"
            )

        questions.append(
            RetrievalQuestion(
                id=identifier,
                question=required("question"),
                expect_document=required("expect_document"),
                expect_facts=tuple(str(fact) for fact in facts),
                min_facts=min_facts,
            )
        )
    return questions


def assert_questions_grounded(
    questions: list[RetrievalQuestion], documents: list[CorpusDocument]
) -> None:
    """The offline coupling guard. Runs inside ``knowledge-docs build``.

    Three failures, all local, all naming the question id:

    - the named document does not exist in the corpus;
    - it exists but is not ``anchor: true`` — an author needs to know which documents carry
      load-bearing sentences *before* rewriting one;
    - an expected fact is no longer in the document verbatim.
    """
    by_filename = {document.filename: document for document in documents}
    problems: list[str] = []

    for question in questions:
        document = by_filename.get(question.expect_document)
        if document is None:
            problems.append(
                f"{question.id}: expects {question.expect_document!r}, which is not in the corpus"
            )
            continue
        if not document.anchor:
            problems.append(
                f"{question.id}: expects {question.expect_document!r}, which is not marked "
                "`anchor: true`. A question may only cite an anchored document, so that its "
                "author knows the sentences are load-bearing."
            )
        for fact in question.expect_facts:
            if not contains_fact(document.body, fact):
                problems.append(
                    f"{question.id}: the fact {fact!r} no longer appears in "
                    f"{question.expect_document}. Either restore the sentence or update the "
                    "question — a live retrieval suite must not be the thing that finds out."
                )

    if problems:
        raise RetrievalError(
            f"{len(problems)} question(s) are no longer grounded in the corpus:\n    "
            + "\n    ".join(problems)
        )


# --- the run ------------------------------------------------------------------


def run_retrieval(
    api: KnowledgeApi,
    questions: list[RetrievalQuestion],
    *,
    workspace_id: str = "",
    target: str = "",
    limit: int = DEFAULT_SEARCH_LIMIT,
    min_score: float = 0.0,
) -> RetrievalReport:
    """Ask each question of the live search index and judge the chunks that come back."""
    report = RetrievalReport(
        target=target, workspace_id=workspace_id, limit=limit, min_score=min_score
    )

    for question in questions:
        results = api.search(question.question, limit=limit, min_score=min_score)
        report.outcomes.append(_judge(question, results))

    return report


def _judge(question: RetrievalQuestion, results: list[SearchResult]) -> RetrievalOutcome:
    ranked = [result for result in results]
    rank: int | None = None
    top_score: float | None = None
    for position, result in enumerate(ranked, start=1):
        if result.filename == question.expect_document:
            rank = position
            top_score = result.score
            break

    # Facts are matched against the chunks of the expected document only. Finding the
    # sentence in some other document is not evidence that this one answers the question.
    haystack = "\n".join(
        result.content for result in ranked if result.filename == question.expect_document
    )
    matched = tuple(fact for fact in question.expect_facts if contains_fact(haystack, fact))
    missing = tuple(fact for fact in question.expect_facts if fact not in matched)

    return RetrievalOutcome(
        question_id=question.id,
        document_found=rank is not None,
        rank=rank,
        top_score=top_score,
        matched_facts=matched,
        missing_facts=missing,
        required_facts=question.required_facts,
        returned=tuple(dict.fromkeys(result.filename for result in ranked)),
    )
