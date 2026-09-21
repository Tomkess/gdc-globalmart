"""Parsing and validating the authored corpus.

The validators here exist because the chunking is not ours: the server splits the document
and only reports how many pieces it made. So the tests that matter are the ones proving the
authoring contract is actually enforced — a section that has outgrown one idea, a document
with two subjects, a heading inside a code fence being mistaken for structure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from globalmart.corpus import (
    MAX_SECTION_CHARS,
    MIN_SECTION_CHARS,
    CorpusError,
    DiataxisKind,
    build_report,
    load_corpus,
    matches,
    parse_corpus_document,
    published_filename,
    slugify,
)

FIXTURES = Path(__file__).parent / "fixtures" / "corpus"
CORPUS = FIXTURES / "corpus"

VALID = """---
kind: reference
title: A title
scope: metrics
owner: analytics-eng
---

# A title

## A section

{body}
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def valid_document(tmp_path: Path, *, body: str = "x" * 400, name: str = "doc.md") -> Path:
    return write(tmp_path / name, VALID.format(body=body))


# --- front matter -------------------------------------------------------------


def test_a_document_without_front_matter_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path / "bare.md", "# A title\n\n## A section\n\n" + "x" * 400 + "\n")
    with pytest.raises(CorpusError, match="no front matter"):
        parse_corpus_document(path)


@pytest.mark.parametrize("key", ["kind", "title", "scope", "owner"])
def test_every_required_front_matter_key_is_required(tmp_path: Path, key: str) -> None:
    text = VALID.format(body="x" * 400)
    text = "\n".join(line for line in text.splitlines() if not line.startswith(f"{key}:")) + "\n"
    path = write(tmp_path / "missing.md", text)
    with pytest.raises(CorpusError, match=key):
        parse_corpus_document(path)


def test_an_unknown_front_matter_key_names_what_is_allowed(tmp_path: Path) -> None:
    """A typo must not silently mean 'documents nothing' — FEAT-008's rule, same reason."""
    text = VALID.format(body="x" * 400).replace("scope: metrics", "scope: metrics\ncoversz: {}")
    path = write(tmp_path / "typo.md", text)
    with pytest.raises(CorpusError, match="unknown front-matter key"):
        parse_corpus_document(path)


def test_an_unknown_diataxis_kind_lists_the_four_valid_ones(tmp_path: Path) -> None:
    text = VALID.format(body="x" * 400).replace("kind: reference", "kind: guide")
    path = write(tmp_path / "kind.md", text)
    with pytest.raises(CorpusError, match="tutorial"):
        parse_corpus_document(path)


def test_covers_rejects_an_unknown_object_class(tmp_path: Path) -> None:
    text = VALID.format(body="x" * 400).replace(
        "owner: analytics-eng", "owner: analytics-eng\ncovers:\n  insights: [a]"
    )
    path = write(tmp_path / "covers.md", text)
    with pytest.raises(CorpusError, match="covers: has unknown key"):
        parse_corpus_document(path)


def test_covers_rejects_a_bare_string_where_a_list_belongs(tmp_path: Path) -> None:
    text = VALID.format(body="x" * 400).replace(
        "owner: analytics-eng", "owner: analytics-eng\ncovers:\n  metrics: m_one"
    )
    path = write(tmp_path / "covers-str.md", text)
    with pytest.raises(CorpusError, match="must be a list"):
        parse_corpus_document(path)


# --- structure ----------------------------------------------------------------


def test_a_second_top_level_heading_is_two_documents(tmp_path: Path) -> None:
    text = VALID.format(body="x" * 400) + "\n# Another subject\n\n## Its section\n\n" + "y" * 400
    path = write(tmp_path / "two.md", text)
    with pytest.raises(CorpusError, match="second top-level"):
        parse_corpus_document(path)


def test_a_document_with_no_sections_is_rejected(tmp_path: Path) -> None:
    text = "---\nkind: reference\ntitle: T\nscope: s\nowner: o\n---\n\n# T\n\n" + "x" * 400 + "\n"
    path = write(tmp_path / "flat.md", text)
    with pytest.raises(CorpusError, match="no '##' sections"):
        parse_corpus_document(path)


def test_a_heading_inside_a_code_fence_is_code_not_structure(tmp_path: Path) -> None:
    """The bug this guards is silent: a fenced `## x` would split the section in two, and the
    second half would be short enough to trip the minimum-length check for no visible reason."""
    body = "x" * 400 + "\n\n```markdown\n## Not a heading\n\nfenced sample\n```\n"
    document = parse_corpus_document(valid_document(tmp_path, body=body))
    assert [section.heading for section in document.sections] == ["A section"]


def test_a_section_over_the_ceiling_names_the_heading(tmp_path: Path) -> None:
    path = valid_document(tmp_path, body="x" * (MAX_SECTION_CHARS + 1))
    with pytest.raises(CorpusError, match="A section"):
        parse_corpus_document(path)


def test_a_section_under_the_floor_is_a_fragment(tmp_path: Path) -> None:
    path = valid_document(tmp_path, body="x" * (MIN_SECTION_CHARS - 1))
    with pytest.raises(CorpusError, match="retrieves as a fragment"):
        parse_corpus_document(path)


def test_duplicate_headings_are_indistinguishable_when_retrieved(tmp_path: Path) -> None:
    text = VALID.format(body="x" * 400) + "\n## A section\n\n" + "y" * 400 + "\n"
    path = write(tmp_path / "dupe.md", text)
    with pytest.raises(CorpusError, match="duplicate heading"):
        parse_corpus_document(path)


def test_a_document_over_the_size_ceiling_is_a_topic_group(tmp_path: Path) -> None:
    sections = "".join(
        f"\n## Section {index}\n\n" + "x" * 2_000 + "\n" for index in range(15)
    )
    text = "---\nkind: reference\ntitle: T\nscope: s\nowner: o\n---\n\n# T\n" + sections
    path = write(tmp_path / "huge.md", text)
    with pytest.raises(CorpusError, match="topic group"):
        parse_corpus_document(path)


# --- naming and identity ------------------------------------------------------


def test_the_published_filename_is_prefixed_kinded_and_slugged() -> None:
    name = published_filename(Path("docs/knowledge-corpus/reference/Net Revenue.md"), DiataxisKind.REFERENCE)
    assert name == "gm-corpus__reference__net-revenue.md"


def test_the_same_stem_under_two_kinds_does_not_collide() -> None:
    reference = published_filename(Path("a/overview.md"), DiataxisKind.REFERENCE)
    explanation = published_filename(Path("b/overview.md"), DiataxisKind.EXPLANATION)
    assert reference != explanation


def test_two_source_paths_publishing_to_one_filename_fail_the_load(tmp_path: Path) -> None:
    """Filename is the API's identity, so the second upsert would overwrite the first."""
    valid_document(tmp_path / "one", name="overview.md")
    valid_document(tmp_path / "two", name="overview.md")
    with pytest.raises(CorpusError, match="both publish as"):
        load_corpus(tmp_path)


def test_the_digest_is_stable_across_parses_and_sensitive_to_one_character(tmp_path: Path) -> None:
    path = valid_document(tmp_path, body="x" * 400)
    first = parse_corpus_document(path).digest
    assert parse_corpus_document(path).digest == first

    write(path, VALID.format(body="x" * 399 + "y"))
    assert parse_corpus_document(path).digest != first


def test_scopes_carry_ownership_kind_topic_and_domains(tmp_path: Path) -> None:
    text = VALID.format(body="x" * 400).replace(
        "owner: analytics-eng", "owner: analytics-eng\ndomains: [finance, sales]"
    )
    document = parse_corpus_document(write(tmp_path / "scoped.md", text))
    assert document.scopes() == (
        "globalmart-corpus",
        "kind/reference",
        "scope/metrics",
        "domain/finance",
        "domain/sales",
    )


def test_slugify_reduces_to_lowercase_and_hyphens() -> None:
    assert slugify("Net Revenue & Margin (v2)") == "net-revenue-margin-v2"


def test_matches_supports_families_without_listing_them() -> None:
    assert matches("m_revenue_*", "m_revenue_net")
    assert not matches("m_revenue_*", "m_cost_net")


# --- the fixture corpus -------------------------------------------------------


def test_the_fixture_corpus_parses_and_reports() -> None:
    documents = load_corpus(CORPUS)
    report = build_report(documents)

    assert report.documents == 5
    assert report.by_kind == {"reference": 3, "explanation": 1, "tutorial": 1}
    assert report.anchors == ("gm-corpus__reference__metric-hierarchy.md",)
    assert report.largest[1] > 0


def test_a_missing_corpus_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match="No corpus directory"):
        load_corpus(tmp_path / "nope")


def test_an_empty_corpus_directory_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(CorpusError, match="holds no .md"):
        load_corpus(tmp_path / "empty")
