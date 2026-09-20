"""Compiling Markdown into memory items.

The test that matters most is `test_a_build_never_touches_an_item_it_does_not_own`. The
compiled items share a directory with whatever a capture pulls back, so a build that owned
the directory rather than the objects would silently delete captured content the first time
it ran.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from globalmart.knowledge import (
    MAX_INSTRUCTION_CHARS,
    OWNER_TAG,
    KnowledgeError,
    MemoryStrategy,
    apply_to_tree,
    build_knowledge,
    compile_documents,
    derive_keywords,
    item_id,
    parse_document,
    slugify,
    source_documents,
)
from globalmart.layout_io import read_tree, write_tree

FIXTURES = Path(__file__).parent / "fixtures" / "knowledge"
MINI = Path(__file__).parent / "fixtures" / "mini_globalmart"


def memory_item(identifier: str, *, tags: list[str]):  # type: ignore[no-untyped-def]
    from gooddata_sdk.catalog.workspace.declarative_model.workspace.analytics_model.analytics_model import (  # noqa: E501
        CatalogDeclarativeMemoryItem,
    )

    return CatalogDeclarativeMemoryItem(
        id=identifier,
        title=identifier,
        instruction="something",
        strategy="AUTO",
        tags=tags,
    )


# --- parsing ------------------------------------------------------------------


def test_sections_split_on_second_level_headings() -> None:
    document = parse_document(FIXTURES / "net_revenue.md")

    assert document.title == "Revenue definitions"
    assert [s.heading for s in document.sections] == ["Net revenue", "Gross revenue"]
    assert "intra-company transfers" in document.sections[0].body


def test_front_matter_is_parsed() -> None:
    document = parse_document(FIXTURES / "with_front_matter.md")

    assert document.domains == ("finance", "sales")
    assert document.keywords == ("margin", "profitability")
    assert document.strategy is MemoryStrategy.ALWAYS


def test_absent_front_matter_defaults_to_auto() -> None:
    """AUTO retrieves on relevance; ALWAYS injects into every prompt and does not scale."""
    document = parse_document(FIXTURES / "net_revenue.md")

    assert document.strategy is MemoryStrategy.AUTO
    assert document.domains == ()


def test_an_unknown_front_matter_key_is_rejected(tmp_path: Path) -> None:
    """The same strict rule domains.yaml uses: a typo must not silently mean 'no domains'."""
    path = tmp_path / "typo.md"
    path.write_text("---\ndomain: [finance]\n---\n\n## A\n\nbody\n", encoding="utf-8")

    with pytest.raises(KnowledgeError, match="domain"):
        parse_document(path)


def test_a_document_with_no_headings_becomes_one_item() -> None:
    """Better than emitting nothing and leaving the author wondering where it went."""
    document = parse_document(FIXTURES / "no_headings.md")

    assert len(document.sections) == 1
    assert "fiscal year starts in February" in document.sections[0].body


def test_duplicate_headings_are_an_error() -> None:
    with pytest.raises(KnowledgeError, match="duplicate heading"):
        parse_document(FIXTURES / "duplicate_headings.md")


def test_an_oversized_section_fails_naming_the_heading() -> None:
    with pytest.raises(KnowledgeError) as excinfo:
        parse_document(FIXTURES / "oversized.md")

    assert "Enormous section" in str(excinfo.value)
    assert str(MAX_INSTRUCTION_CHARS) in str(excinfo.value)
    assert "Split it" in str(excinfo.value)


def test_a_paragraph_just_under_the_limit_passes(tmp_path: Path) -> None:
    path = tmp_path / "big.md"
    path.write_text(f"## Large\n\n{'x' * (MAX_INSTRUCTION_CHARS - 10)}\n", encoding="utf-8")

    assert len(parse_document(path).sections) == 1


def test_a_section_may_exceed_the_limit_if_its_paragraphs_do_not(tmp_path: Path) -> None:
    """The cap is per item, and an item is a paragraph — so a long section is fine."""
    path = tmp_path / "many.md"
    body = "\n\n".join("x" * 200 for _ in range(5))
    path.write_text(f"## Many\n\n{body}\n", encoding="utf-8")

    (section,) = parse_document(path).sections
    assert len(section.body) > MAX_INSTRUCTION_CHARS
    assert len(section.paragraphs()) == 5


def test_a_heading_inside_a_code_fence_is_not_a_heading(tmp_path: Path) -> None:
    path = tmp_path / "fenced.md"
    path.write_text(
        "## Real\n\n```\n## not a heading\n```\n\nafter\n", encoding="utf-8"
    )
    document = parse_document(path)

    assert [s.heading for s in document.sections] == ["Real"]
    assert "## not a heading" in document.sections[0].body


def test_an_unknown_strategy_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.md"
    path.write_text("---\nstrategy: SOMETIMES\n---\n\n## A\n\nbody\n", encoding="utf-8")

    with pytest.raises(KnowledgeError, match="SOMETIMES"):
        parse_document(path)


# --- ids and keywords ---------------------------------------------------------


def test_slugify_reduces_to_a_safe_id() -> None:
    assert slugify("Net Revenue — what it excludes!") == "net_revenue_what_it_excludes"


def test_ids_are_deterministic_and_derived_from_file_and_heading() -> None:
    document = parse_document(FIXTURES / "net_revenue.md")

    assert item_id(document, document.sections[0]) == "net_revenue_net_revenue"
    assert item_id(document, document.sections[0], 0, 2) == "net_revenue_net_revenue_01"
    assert item_id(document, document.sections[0]) == item_id(document, document.sections[0])


def test_keywords_come_from_the_heading_and_the_author() -> None:
    assert derive_keywords("Gross margin bridge", ("profitability",)) == (
        "bridge",
        "gross",
        "margin",
        "profitability",
    )


def test_stop_words_are_dropped_but_explicit_keywords_always_survive() -> None:
    """Derived keywords are a default; the author's are the mechanism."""
    derived = derive_keywords("What it excludes", ("the",))

    assert "what" not in derived
    assert "excludes" in derived
    assert "the" in derived


# --- compiling ----------------------------------------------------------------


def test_compiled_items_carry_the_owner_tag_and_domain_tags() -> None:
    items = compile_documents([FIXTURES / "with_front_matter.md"])

    (item,) = items
    assert OWNER_TAG in item.tags
    assert "domain/finance" in item.tags
    assert "domain/sales" in item.tags


def test_compiled_items_are_sorted_by_id() -> None:
    """Sorted emission is what keeps a rebuild out of the diff."""
    items = compile_documents(source_documents(FIXTURES.parent / "knowledge_ok"))
    ids = [item.id for item in items]

    assert ids == sorted(ids)
    assert len(ids) == 4


def test_each_paragraph_becomes_its_own_item() -> None:
    """The unit is a paragraph, because the API caps an instruction at 255 characters."""
    items = compile_documents([FIXTURES / "net_revenue.md"])
    ids = [item.id for item in items]

    assert ids == [
        "net_revenue_gross_revenue",
        "net_revenue_net_revenue_01",
        "net_revenue_net_revenue_02",
    ]
    assert all(len(item.instruction) <= MAX_INSTRUCTION_CHARS for item in items)
    # A single-paragraph section keeps a clean id; only a split section gets a suffix.
    assert "Gross revenue is the sum" in items[0].instruction


def test_the_description_carries_provenance() -> None:
    """Someone reading the item in the org should be able to find the Markdown."""
    (item,) = compile_documents([FIXTURES / "with_front_matter.md"])

    assert "Margin" in item.description
    assert "with_front_matter.md" in item.description


# --- ownership: the one that matters ------------------------------------------


def test_a_build_never_touches_an_item_it_does_not_own() -> None:
    """A captured or hand-authored item shares the channel and must survive a build.

    Positional ownership — "this build owns everything in `memory_items/`" — would delete
    the captured item here. That is the design this test exists to prevent.
    """
    model = read_tree(MINI)
    captured = memory_item("captured_by_bootstrap", tags=["area/sales"])
    stale = memory_item("net_revenue_removed_section", tags=[OWNER_TAG])
    model.analytics.memory_items = [captured, stale]

    items = compile_documents([FIXTURES / "net_revenue.md"])
    report = apply_to_tree(model, items)

    surviving = {item.id for item in model.analytics.memory_items}
    assert "captured_by_bootstrap" in surviving          # untagged: untouched
    assert "net_revenue_removed_section" not in surviving  # owned and gone: removed
    assert report.removed == ["net_revenue_removed_section"]


def test_a_removed_section_removes_its_item() -> None:
    model = read_tree(MINI)
    model.analytics.memory_items = list(compile_documents([FIXTURES / "net_revenue.md"]))

    report = apply_to_tree(model, compile_documents([FIXTURES / "with_front_matter.md"]))

    assert sorted(report.removed) == [
        "net_revenue_gross_revenue",
        "net_revenue_net_revenue_01",
        "net_revenue_net_revenue_02",
    ]


def test_an_unchanged_build_reports_no_change() -> None:
    model = read_tree(MINI)
    items = compile_documents([FIXTURES / "net_revenue.md"])
    apply_to_tree(model, items)

    report = apply_to_tree(model, compile_documents([FIXTURES / "net_revenue.md"]))

    assert not report.changed
    assert len(report.unchanged) == 3


def test_an_edited_section_is_reported_as_updated(tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    source.write_text("## A heading\n\noriginal body\n", encoding="utf-8")

    model = read_tree(MINI)
    apply_to_tree(model, compile_documents([source]))

    source.write_text("## A heading\n\nrewritten body\n", encoding="utf-8")
    report = apply_to_tree(model, compile_documents([source]))

    assert report.updated == ["doc_a_heading"]
    assert report.changed


# --- the tree -----------------------------------------------------------------


def _tree_copy(tmp_path: Path) -> Path:
    destination = tmp_path / "tree"
    shutil.copytree(MINI, destination)
    return destination


def test_building_writes_items_into_the_tree(tmp_path: Path) -> None:
    tree = _tree_copy(tmp_path)

    report = build_knowledge(source_dir=FIXTURES.parent / "knowledge_ok", layout_path=tree)

    assert report.items > 0
    written = sorted(p.stem for p in (tree / "analytics_model" / "memory_items").glob("*.yaml"))
    assert "net_revenue_net_revenue_01" in written


def test_two_builds_are_byte_identical(tmp_path: Path) -> None:
    tree = _tree_copy(tmp_path)
    source = FIXTURES.parent / "knowledge_ok"

    build_knowledge(source_dir=source, layout_path=tree)
    first = {p: p.read_bytes() for p in sorted(tree.rglob("*.yaml"))}
    build_knowledge(source_dir=source, layout_path=tree)
    second = {p: p.read_bytes() for p in sorted(tree.rglob("*.yaml"))}

    assert first == second


def test_check_reports_drift_and_writes_nothing(tmp_path: Path) -> None:
    tree = _tree_copy(tmp_path)
    source = FIXTURES.parent / "knowledge_ok"
    before = {p: p.read_bytes() for p in sorted(tree.rglob("*.yaml"))}

    report = build_knowledge(source_dir=source, layout_path=tree, check=True)

    assert report.changed
    after = {p: p.read_bytes() for p in sorted(tree.rglob("*.yaml"))}
    assert after == before


def test_check_is_clean_once_the_tree_is_current(tmp_path: Path) -> None:
    tree = _tree_copy(tmp_path)
    source = FIXTURES.parent / "knowledge_ok"

    build_knowledge(source_dir=source, layout_path=tree)
    report = build_knowledge(source_dir=source, layout_path=tree, check=True)

    assert not report.changed


def test_a_hand_edited_item_is_overwritten(tmp_path: Path) -> None:
    """The Markdown is the source of truth; the YAML is output."""
    tree = _tree_copy(tmp_path)
    source = FIXTURES.parent / "knowledge_ok"
    build_knowledge(source_dir=source, layout_path=tree)

    victim = tree / "analytics_model" / "memory_items" / "net_revenue_net_revenue_01.yaml"
    victim.write_text(victim.read_text(encoding="utf-8") + "\nhandEdited: true\n", encoding="utf-8")

    build_knowledge(source_dir=source, layout_path=tree)

    assert "handEdited" not in victim.read_text(encoding="utf-8")


def test_the_capture_then_build_cycle_converges(tmp_path: Path) -> None:
    """Build, round-trip through the writer and reader, build again: no change.

    This is the capture-then-build cycle without a host. It is what makes the ordering rule
    safe rather than merely documented.
    """
    tree = _tree_copy(tmp_path)
    source = FIXTURES.parent / "knowledge_ok"

    build_knowledge(source_dir=source, layout_path=tree)
    model = read_tree(tree)
    write_tree(model, tree)

    report = build_knowledge(source_dir=source, layout_path=tree, check=True)
    assert not report.changed


def test_a_missing_source_directory_is_named(tmp_path: Path) -> None:
    with pytest.raises(KnowledgeError, match="No knowledge source"):
        build_knowledge(source_dir=tmp_path / "nope", layout_path=_tree_copy(tmp_path))


# --- the point of the domain tags ---------------------------------------------


def test_feat004_filters_the_compiled_items_by_domain(tmp_path: Path) -> None:
    """The first real content FEAT-004's AI filtering has ever had to filter."""
    import dataclasses

    from globalmart.ai_context import filter_ai_context
    from globalmart.domains import AiSelection, load_domains

    manifest = load_domains(Path(__file__).parent / "fixtures" / "mini_domains" / "domains.yaml")
    model = read_tree(MINI)
    model.analytics.memory_items = list(compile_documents([FIXTURES / "with_front_matter.md"]))

    # The fixture manifest shares a parameter the mini parent does not carry; clear the
    # shared block so this test is about domain tagging and nothing else.
    from globalmart.domains import SharedSelection

    bare = dataclasses.replace(manifest, shared=SharedSelection())
    finance = dataclasses.replace(
        bare.by_key("sales"), ai=AiSelection(memory_item_tags=("domain/finance",))
    )
    other = dataclasses.replace(bare.by_key("hr"), ai=AiSelection(memory_item_tags=("domain/hr",)))

    assert filter_ai_context(model, finance, bare).ids() == {
        "with_front_matter_gross_margin_bridge"
    }
    assert filter_ai_context(model, other, bare).ids() == set()
