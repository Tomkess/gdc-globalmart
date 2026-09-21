"""Answer-level validation, offline.

Two halves. `assert_questions_grounded` is the offline guard that runs inside
`knowledge-docs build` — it is what stops the question set rotting silently when someone
rewrites a load-bearing sentence. `run_retrieval` is the live half, exercised here against a
stubbed search so the judging logic is tested without a host.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from globalmart.corpus import CorpusDocument, load_corpus
from globalmart.knowledge_docs import SearchResult
from globalmart.retrieval import (
    RetrievalError,
    RetrievalQuestion,
    assert_questions_grounded,
    contains_fact,
    load_questions,
    normalise,
    run_retrieval,
)
from tests.test_knowledge_docs import FakeKnowledgeApi

FIXTURES = Path(__file__).parent / "fixtures" / "corpus"
CORPUS = FIXTURES / "corpus"
QUESTIONS = FIXTURES / "corpus-questions.yaml"
ANCHOR = "gm-corpus__reference__metric-hierarchy.md"


@pytest.fixture
def documents() -> list[CorpusDocument]:
    return load_corpus(CORPUS)


def chunk(filename: str, content: str, *, score: float = 0.9, index: int = 0) -> SearchResult:
    return SearchResult(
        id="doc-1",
        filename=filename,
        content=content,
        score=score,
        chunk_index=index,
        total_chunks=3,
    )


# --- the question set ---------------------------------------------------------


def test_the_fixture_question_set_loads() -> None:
    questions = load_questions(QUESTIONS)
    assert [q.id for q in questions] == ["q_net_revenue_transfers", "q_nps_scale"]
    assert questions[0].required_facts == 1
    assert questions[1].required_facts == 1  # min_facts: 1 out of two facts


def test_a_missing_question_set_is_not_an_error(tmp_path: Path) -> None:
    assert load_questions(tmp_path / "absent.yaml") == []


def test_a_question_with_no_expected_facts_is_not_a_test(tmp_path: Path) -> None:
    path = tmp_path / "q.yaml"
    path.write_text(
        "questions:\n  - id: q\n    question: why\n    expect_document: d.md\n", encoding="utf-8"
    )
    with pytest.raises(RetrievalError, match="not a test"):
        load_questions(path)


def test_a_duplicate_question_id_raises(tmp_path: Path) -> None:
    path = tmp_path / "q.yaml"
    path.write_text(
        "questions:\n"
        "  - id: q\n    question: a\n    expect_document: d.md\n    expect_facts: [x]\n"
        "  - id: q\n    question: b\n    expect_document: d.md\n    expect_facts: [y]\n",
        encoding="utf-8",
    )
    with pytest.raises(RetrievalError, match="duplicate question id"):
        load_questions(path)


def test_min_facts_beyond_the_fact_count_raises(tmp_path: Path) -> None:
    path = tmp_path / "q.yaml"
    path.write_text(
        "questions:\n  - id: q\n    question: a\n    expect_document: d.md\n"
        "    expect_facts: [x]\n    min_facts: 3\n",
        encoding="utf-8",
    )
    with pytest.raises(RetrievalError, match="min_facts must be between"):
        load_questions(path)


# --- the offline coupling guard ----------------------------------------------


def test_the_fixture_question_set_is_grounded(documents: list[CorpusDocument]) -> None:
    assert_questions_grounded(load_questions(QUESTIONS), documents)


def test_a_question_naming_an_absent_document_fails_at_build_time(
    documents: list[CorpusDocument],
) -> None:
    question = RetrievalQuestion(
        id="q_gone",
        question="anything",
        expect_document="gm-corpus__reference__never-written.md",
        expect_facts=("x",),
    )
    with pytest.raises(RetrievalError, match="not in the corpus"):
        assert_questions_grounded([question], documents)


def test_a_question_citing_an_unanchored_document_fails(documents: list[CorpusDocument]) -> None:
    """An author must know which documents carry load-bearing sentences before rewriting one."""
    question = RetrievalQuestion(
        id="q_unanchored",
        question="anything",
        expect_document="gm-corpus__reference__data-model.md",
        expect_facts=("fiscal year starts in February",),
    )
    with pytest.raises(RetrievalError, match="anchor: true"):
        assert_questions_grounded([question], documents)


def test_an_edited_fact_fails_offline_naming_the_question(
    documents: list[CorpusDocument],
) -> None:
    """The whole point: a live LLM suite must not be the thing that discovers this."""
    question = RetrievalQuestion(
        id="q_stale_fact",
        question="anything",
        expect_document=ANCHOR,
        expect_facts=("excludes inter-company transfers",),  # 'inter', not 'intra'
    )
    with pytest.raises(RetrievalError, match="q_stale_fact"):
        assert_questions_grounded([question], documents)


# --- fact matching ------------------------------------------------------------


def test_matching_survives_reflowing_and_capitalisation() -> None:
    assert contains_fact(
        "Net revenue\n  EXCLUDES   intra-company transfers.",
        "excludes intra-company transfers",
    )


def test_matching_does_not_survive_a_rewrite() -> None:
    """Tolerating paraphrase would tolerate the fact changing meaning."""
    assert not contains_fact(
        "Net revenue leaves out transfers between group companies.",
        "excludes intra-company transfers",
    )


def test_normalise_collapses_whitespace_and_casefolds() -> None:
    assert normalise("  A\n\tB  ") == "a b"


# --- judging a live run -------------------------------------------------------


def test_a_question_passes_when_its_document_and_facts_come_back() -> None:
    api = FakeKnowledgeApi()
    api.search_results = [chunk(ANCHOR, "Net revenue excludes intra-company transfers, so ...")]
    questions = [
        RetrievalQuestion(
            id="q", question="?", expect_document=ANCHOR, expect_facts=("excludes intra-company transfers",)
        )
    ]

    report = run_retrieval(api, questions)

    assert report.passed
    outcome = report.outcomes[0]
    assert outcome.rank == 1
    assert outcome.top_score == pytest.approx(0.9)


def test_a_question_fails_when_the_document_is_not_returned() -> None:
    api = FakeKnowledgeApi()
    api.search_results = [chunk("gm-corpus__reference__data-model.md", "dimensions and facts")]
    questions = [
        RetrievalQuestion(id="q", question="?", expect_document=ANCHOR, expect_facts=("anything",))
    ]

    report = run_retrieval(api, questions)

    assert not report.passed
    assert report.outcomes[0].document_found is False
    assert report.outcomes[0].returned == ("gm-corpus__reference__data-model.md",)


def test_facts_found_in_another_document_do_not_count() -> None:
    """Right sentence, wrong document — that is not evidence this document answers it."""
    api = FakeKnowledgeApi()
    api.search_results = [
        chunk(ANCHOR, "some other paragraph entirely", score=0.7),
        chunk("gm-corpus__explanation__bonus-cost.md", "excludes intra-company transfers", score=0.6),
    ]
    questions = [
        RetrievalQuestion(
            id="q", question="?", expect_document=ANCHOR, expect_facts=("excludes intra-company transfers",)
        )
    ]

    report = run_retrieval(api, questions)

    assert not report.passed
    assert report.outcomes[0].document_found is True
    assert report.outcomes[0].missing_facts == ("excludes intra-company transfers",)


def test_min_facts_lets_a_question_accept_one_of_several() -> None:
    api = FakeKnowledgeApi()
    api.search_results = [chunk(ANCHOR, "the eleven-point scale as stored")]
    questions = [
        RetrievalQuestion(
            id="q",
            question="?",
            expect_document=ANCHOR,
            expect_facts=("eleven-point scale", "promoter-minus-detractor"),
            min_facts=1,
        )
    ]

    report = run_retrieval(api, questions)

    assert report.passed
    assert report.outcomes[0].missing_facts == ("promoter-minus-detractor",)


def test_facts_are_gathered_across_several_chunks_of_one_document() -> None:
    api = FakeKnowledgeApi()
    api.search_results = [
        chunk(ANCHOR, "the eleven-point scale as stored", index=0),
        chunk(ANCHOR, "without converting to the promoter-minus-detractor form", index=1),
    ]
    questions = [
        RetrievalQuestion(
            id="q",
            question="?",
            expect_document=ANCHOR,
            expect_facts=("eleven-point scale", "promoter-minus-detractor"),
        )
    ]

    assert run_retrieval(api, questions).passed


def test_the_search_limit_is_passed_through() -> None:
    api = FakeKnowledgeApi()
    api.search_results = [chunk(ANCHOR, "x") for _ in range(20)]
    questions = [
        RetrievalQuestion(id="q", question="?", expect_document=ANCHOR, expect_facts=("x",))
    ]

    run_retrieval(api, questions, limit=3)

    assert api.searches == ["?"]


def test_the_report_names_what_failed_and_why() -> None:
    api = FakeKnowledgeApi()
    api.search_results = [chunk("gm-corpus__reference__data-model.md", "unrelated")]
    questions = [
        RetrievalQuestion(
            id="q_missing", question="?", expect_document=ANCHOR, expect_facts=("a fact",)
        )
    ]

    lines = "\n".join(run_retrieval(api, questions).summary_lines())

    assert "q_missing" in lines
    assert "expected document not in the top" in lines
