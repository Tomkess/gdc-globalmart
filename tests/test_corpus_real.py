"""The guard against the real parent tree and the real corpus.

This is FEAT-015's acceptance criterion, and it runs in CI: every object in the committed
parent workspace is documented by `docs/knowledge-corpus/` or excluded in
`config/corpus.yaml` with a written reason. A PR that adds a metric, renames a dataset or
deletes a dashboard without touching the documentation fails here.

The companion of `test_domains_real.py`, which asks the same question about domain
membership. Skipped cleanly when an artifact is missing, so the suite stays runnable on a
fresh checkout.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from globalmart.corpus import load_corpus
from globalmart.corpus_coverage import (
    check_corpus_coverage,
    load_corpus_manifest,
    raise_for_corpus_report,
)
from globalmart.layout_io import read_tree
from globalmart.retrieval import assert_questions_grounded, load_questions

REPO = Path(__file__).resolve().parents[1]
LAYOUT = REPO / "layouts" / "workspaces" / "globalmart"
CORPUS = REPO / "docs" / "knowledge-corpus"
MANIFEST = REPO / "config" / "corpus.yaml"
QUESTIONS = REPO / "config" / "corpus-questions.yaml"

pytestmark = pytest.mark.skipif(
    not (LAYOUT.exists() and CORPUS.exists()),
    reason="the real parent tree or docs/knowledge-corpus/ is not present",
)


@pytest.fixture(scope="module")
def documents():  # type: ignore[no-untyped-def]
    return load_corpus(CORPUS)


@pytest.fixture(scope="module")
def report(documents):  # type: ignore[no-untyped-def]
    return check_corpus_coverage(read_tree(LAYOUT), documents, load_corpus_manifest(MANIFEST))


def test_the_corpus_parses(documents) -> None:  # type: ignore[no-untyped-def]
    """Every authored document satisfies the authoring contract."""
    assert len(documents) >= 30
    assert {d.kind.value for d in documents} == {
        "reference",
        "explanation",
        "how_to",
        "tutorial",
    }


def test_every_topic_group_is_present(documents) -> None:  # type: ignore[no-untyped-def]
    """The corpus describes the whole workspace, not one corner of it."""
    scopes = {d.scope for d in documents}
    assert scopes == {
        "data-model",
        "metrics",
        "dashboards",
        "domains",
        "warehouse",
        "ai-context",
        "getting-started",
    }


def test_every_domain_has_a_dashboard_document(documents) -> None:  # type: ignore[no-untyped-def]
    """Twelve domains, twelve dashboard documents — read from the manifest, not hardcoded."""
    from globalmart.domains import load_domains

    manifest_path = REPO / "config" / "domains.yaml"
    if not manifest_path.exists():
        pytest.skip("config/domains.yaml is not present")

    manifest = load_domains(manifest_path)
    documented = {
        key
        for document in documents
        if document.scope == "dashboards"
        for key in document.domains
    }
    assert documented == set(manifest.keys())


def test_the_whole_workspace_is_documented(report) -> None:  # type: ignore[no-untyped-def]
    """The gate. Strict, so a placeholder exclusion reason fails too."""
    assert report.by_class["datasets"].total == 227
    assert report.by_class["metrics"].total == 1091
    assert report.by_class["visualizations"].total == 384
    assert report.by_class["dashboards"].total == 32

    raise_for_corpus_report(report, strict=True)


def test_nothing_is_excluded_today(report) -> None:  # type: ignore[no-untyped-def]
    """Measured fact, not a rule.

    Full coverage with an empty `config/corpus.yaml` is the current state. If an object
    genuinely earns an exclusion this test is the one to update — deliberately, which is the
    point of writing the reason down.
    """
    assert all(cov.excluded == {} for cov in report.by_class.values())


def test_the_question_set_is_grounded(documents) -> None:  # type: ignore[no-untyped-def]
    """Offline. Every expected fact still appears verbatim in its anchored document."""
    questions = load_questions(QUESTIONS)
    assert len(questions) >= 8
    assert_questions_grounded(questions, documents)


def test_every_question_cites_a_distinct_enough_document(documents) -> None:  # type: ignore[no-untyped-def]
    """A suite that only ever asks about one document proves very little."""
    questions = load_questions(QUESTIONS)
    cited = {q.expect_document for q in questions}
    assert len(cited) >= 6
