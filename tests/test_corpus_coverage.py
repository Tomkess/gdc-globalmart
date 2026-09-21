"""Coverage of the workspace by the corpus, and the manifest that excuses the gaps.

Two tests here carry the feature's actual claim, and they are the symmetrical pair:
`test_a_covers_pattern_matching_nothing_is_fatal` (a metric was renamed, its document was
not) and `test_an_exclusion_matching_nothing_is_fatal` (an object was deleted, its excuse
outlived it). Everything else is bookkeeping around them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from globalmart.corpus import load_corpus
from globalmart.corpus_coverage import (
    CorpusCoverageError,
    CorpusExclusion,
    CorpusManifest,
    CorpusManifestError,
    check_corpus_coverage,
    load_corpus_manifest,
    raise_for_corpus_report,
    workspace_census,
)
from globalmart.layout_io import read_tree

FIXTURES = Path(__file__).parent / "fixtures" / "corpus"
CORPUS = FIXTURES / "corpus"
MINI = Path(__file__).parent / "fixtures" / "mini_globalmart"


@pytest.fixture
def model():  # type: ignore[no-untyped-def]
    return read_tree(MINI)


@pytest.fixture
def documents():  # type: ignore[no-untyped-def]
    return load_corpus(CORPUS)


@pytest.fixture
def manifest() -> CorpusManifest:
    return load_corpus_manifest(FIXTURES / "corpus.yaml")


# --- the manifest loader ------------------------------------------------------


def test_the_fixture_manifest_loads(manifest: CorpusManifest) -> None:
    assert manifest.version == 1
    assert len(manifest.metrics) == 3
    assert len(manifest.visualizations) == 1
    assert manifest.exclusions("dashboards") == ()


def test_a_missing_manifest_is_not_an_error(tmp_path: Path) -> None:
    """A corpus with nothing excluded is the goal state, not a configuration error."""
    loaded = load_corpus_manifest(tmp_path / "absent.yaml")
    assert loaded.metrics == ()
    assert loaded.path is None


def test_an_unknown_manifest_key_raises(tmp_path: Path) -> None:
    path = tmp_path / "corpus.yaml"
    path.write_text("version: 1\nexclusion: {}\n", encoding="utf-8")
    with pytest.raises(CorpusManifestError, match="unknown key"):
        load_corpus_manifest(path)


def test_an_unknown_object_class_raises(tmp_path: Path) -> None:
    path = tmp_path / "corpus.yaml"
    path.write_text("version: 1\nexclusions:\n  insights:\n    - id: a\n      reason: b\n", encoding="utf-8")
    with pytest.raises(CorpusManifestError, match="unknown class"):
        load_corpus_manifest(path)


def test_an_exclusion_without_a_reason_raises(tmp_path: Path) -> None:
    path = tmp_path / "corpus.yaml"
    path.write_text("version: 1\nexclusions:\n  metrics:\n    - id: m_one\n", encoding="utf-8")
    with pytest.raises(CorpusManifestError, match="costs a sentence"):
        load_corpus_manifest(path)


@pytest.mark.parametrize("reason", ["TODO", "tbd", "n/a", "  ", "-"])
def test_placeholder_reasons_are_recognised(reason: str) -> None:
    """The rule is imported from domains.py, not re-derived — one definition of 'TODO'."""
    assert CorpusExclusion(id="m", reason=reason).reason_is_placeholder()


def test_a_real_sentence_is_not_a_placeholder() -> None:
    assert not CorpusExclusion(
        id="m", reason="Superseded by m_net_revenue in the 2026-06 model revision."
    ).reason_is_placeholder()


# --- the check ----------------------------------------------------------------


def test_the_census_counts_date_instances_as_datasets(model) -> None:  # type: ignore[no-untyped-def]
    census = workspace_census(model)
    assert "fiscal_date" in census["datasets"]
    assert len(census["metrics"]) == 8


def test_the_fixture_corpus_fully_covers_the_mini_workspace(model, documents, manifest) -> None:  # type: ignore[no-untyped-def]
    report = check_corpus_coverage(model, documents, manifest)

    assert report.uncovered_total() == 0
    assert report.unknown_covers == {}
    assert report.unmatched_exclusions == {}
    assert report.is_clean(strict=True)
    raise_for_corpus_report(report, strict=True)


def test_a_tutorial_covering_nothing_is_reported_never_fatal(model, documents, manifest) -> None:  # type: ignore[no-untyped-def]
    report = check_corpus_coverage(model, documents, manifest)
    assert report.documents_covering_nothing == ("gm-corpus__tutorial__getting-started.md",)
    assert report.is_clean()


def test_an_undocumented_metric_is_uncovered_and_fatal(model, documents) -> None:  # type: ignore[no-untyped-def]
    empty = CorpusManifest(version=1, parent_workspace_id="globalmart")
    report = check_corpus_coverage(model, documents, empty)

    assert "average_l1_bonus_cost_duplicate" in report.by_class["metrics"].uncovered
    assert not report.is_clean()
    with pytest.raises(CorpusCoverageError, match="documented by no corpus document"):
        raise_for_corpus_report(report)


def test_a_covers_pattern_matching_nothing_is_fatal(model, manifest, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """The renamed-metric case. This is the check that catches real documentation drift."""
    document = (tmp_path / "reference").joinpath("renamed.md")
    document.parent.mkdir(parents=True)
    document.write_text(
        "---\nkind: reference\ntitle: T\nscope: metrics\nowner: o\n"
        "covers:\n  metrics: [m_was_renamed_last_week]\n---\n\n# T\n\n## S\n\n" + "x" * 400 + "\n",
        encoding="utf-8",
    )
    report = check_corpus_coverage(model, load_corpus(tmp_path), manifest)

    assert "metrics:m_was_renamed_last_week" in report.unknown_covers
    with pytest.raises(CorpusCoverageError, match="renamed or deleted"):
        raise_for_corpus_report(report)


def test_an_exclusion_matching_nothing_is_fatal(model, documents) -> None:  # type: ignore[no-untyped-def]
    """The stale-excuse case: the object is gone and its exclusion outlived it."""
    stale = CorpusManifest(
        version=1,
        parent_workspace_id="globalmart",
        metrics=(CorpusExclusion(id="m_deleted_in_june", reason="Removed with the old ledger."),),
    )
    report = check_corpus_coverage(model, documents, stale)

    assert "metrics:m_deleted_in_june" in report.unmatched_exclusions
    with pytest.raises(CorpusCoverageError, match="excuse outlived it"):
        raise_for_corpus_report(report)


def test_a_placeholder_reason_passes_plain_and_fails_strict(model, documents) -> None:  # type: ignore[no-untyped-def]
    lazy = CorpusManifest(
        version=1,
        parent_workspace_id="globalmart",
        metrics=(
            CorpusExclusion(id="average_l1_bonus_cost_duplicate", reason="TODO"),
            CorpusExclusion(id="average_total_bonus_cost_variant", reason="Variant fixture."),
            CorpusExclusion(
                id="average_total_sales_amount_daily_store_sales_copy", reason="Copy fixture."
            ),
        ),
        visualizations=(CorpusExclusion(id="viz_orphan_0001", reason="On no dashboard."),),
    )
    report = check_corpus_coverage(model, documents, lazy)

    assert report.is_clean()
    assert not report.is_clean(strict=True)
    raise_for_corpus_report(report)
    with pytest.raises(CorpusCoverageError, match="placeholder reason"):
        raise_for_corpus_report(report, strict=True)


def test_one_object_documented_twice_reports_both_documents(model, manifest, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    for name in ("first", "second"):
        path = tmp_path / "reference" / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\nkind: reference\ntitle: T\nscope: metrics\nowner: o\n"
            "covers:\n  metrics: [average_total_nps_score]\n---\n\n# T\n\n## S\n\n"
            + "x" * 400
            + "\n",
            encoding="utf-8",
        )
    report = check_corpus_coverage(model, load_corpus(tmp_path), manifest)

    assert len(report.by_class["metrics"].documented["average_total_nps_score"]) == 2


def test_documentation_wins_over_an_exclusion(model, documents) -> None:  # type: ignore[no-untyped-def]
    """Writing about an excluded object must not fail a build for having written too much."""
    overlapping = CorpusManifest(
        version=1,
        parent_workspace_id="globalmart",
        metrics=(
            CorpusExclusion(id="average_total_nps_score", reason="Excluded, then documented anyway."),
            CorpusExclusion(id="average_l1_bonus_cost_duplicate", reason="Duplicate fixture."),
            CorpusExclusion(id="average_total_bonus_cost_variant", reason="Variant fixture."),
            CorpusExclusion(
                id="average_total_sales_amount_daily_store_sales_copy", reason="Copy fixture."
            ),
        ),
        visualizations=(CorpusExclusion(id="viz_orphan_0001", reason="On no dashboard."),),
    )
    report = check_corpus_coverage(model, documents, overlapping)

    metrics = report.by_class["metrics"]
    assert "average_total_nps_score" in metrics.documented
    assert "average_total_nps_score" not in metrics.excluded
    assert report.is_clean()


def test_the_report_serialises_for_json_output(model, documents, manifest) -> None:  # type: ignore[no-untyped-def]
    payload = check_corpus_coverage(model, documents, manifest).as_dict()
    assert payload["by_class"]["metrics"]["total"] == 8
    assert isinstance(payload["by_class"]["metrics"]["documented"], dict)
