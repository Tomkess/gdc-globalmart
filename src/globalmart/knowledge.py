"""Compile authored Markdown into AI memory items inside the captured layout.

GlobalMart's assistant knows only what the semantic layer names. Nothing tells it that net
revenue excludes intra-company transfers, or which of two similarly named metrics an analyst
means. This is the path from a document into the workspace.

**This module is the short-directive channel, not the only one.** When it was written it
recorded that "there is no document-upload API… checked against the API client and gdc-nas,
2026-09-18". That is **superseded**: GoodData Cloud has an AI Knowledge *document* API
(`/api/v1/ai/workspaces/{id}/knowledge/documents`, shipped 2026-03-26, re-verified
2026-09-21), and FEAT-015's `knowledge_docs.py` publishes whole Markdown files through it.
See ADR 009.

The two channels are siblings, and a fact belongs to exactly one of them:

- **here** — a paragraph under 255 characters, a standing directive, carried inside the
  layout tree, copied into each child by the splitter, selected by tag;
- **`knowledge_docs.py`** — a whole document that explains something, published by its own
  API call, inherited by children at query time, grouped by `scopes`.

Write a rule the assistant should always obey here. Write documentation a person or an agent
should be able to look up there. Restating one in the other is the duplication this split
exists to prevent.

Memory items live under `analytics`, not `ldm` — knowledge is analytics-layer content, so
nothing here touches the semantic model. Because the compiled items land in the layout tree,
everything downstream already works: FEAT-001 writes them byte-stably and counts them,
FEAT-002 publishes them to any org with no new code path, FEAT-004 filters them per domain
by tag.

**Ownership is marked, not positional.** Every compiled item carries the reserved tag
``knowledge``, and a build reconciles only against items carrying it. The alternative —
"this build owns everything in `memory_items/`" — would let a build delete a captured or
hand-authored item that happens to share the directory. Ownership is a property of the
object, so the rule survives a re-capture.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from globalmart.config import GlobalmartError

#: The reserved tag that marks an item as compiled by this feature. A memory item without it
#: is someone else's and is never touched.
OWNER_TAG = "knowledge"
DOMAIN_TAG_PREFIX = "domain/"

#: A document that names no domains is universal — metric naming conventions apply
#: everywhere — so it gets this tag and `domains.yaml`'s `shared.ai` selects it into every
#: child. The alternative, letting "no domains" mean "no domain", would leave the item
#: uncovered and fail FEAT-003's deny-by-default AI check, which is the correct outcome for
#: an *unclassified* item but the wrong one for a deliberately universal one. Explicit
#: either way: a document is universal or it lists its domains.
SHARED_TAG = "knowledge/shared"

#: The API's hard cap on `instruction`, discovered by being rejected by it: a memory item is
#: a short directive, not a document. `description` allows 10000 and carries provenance.
#:
#: This is why the unit of compilation is a **paragraph**, not a `##` section. Section-level
#: chunking was the spec's plan and it is simply not expressible — a section that fits in 255
#: characters is a paragraph with extra steps.
MAX_INSTRUCTION_CHARS = 255
MAX_DESCRIPTION_CHARS = 10000

DEFAULT_SOURCE_DIR = Path("docs/knowledge")

_FRONT_MATTER_KEYS = frozenset({"domains", "keywords", "strategy", "split_level"})

#: Dropped when deriving keywords from a heading. Deliberately short — an over-eager stop
#: list silently removes the term someone would actually search for.
_STOP_WORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "is",
        "it", "of", "on", "or", "that", "the", "to", "what", "when", "which", "with",
    }
)


class KnowledgeError(GlobalmartError):
    """A source document cannot be compiled."""


class MemoryStrategy(StrEnum):
    """Required by the API, with no default.

    ``ALWAYS`` injects the item into every prompt; ``AUTO`` retrieves it on relevance.
    ``AUTO`` is the default because it is the one that scales — ``ALWAYS`` is right for a
    short glossary and wrong for anything longer.
    """

    ALWAYS = "ALWAYS"
    AUTO = "AUTO"


@dataclass(frozen=True)
class KnowledgeSection:
    heading: str
    body: str
    level: int

    def paragraphs(self) -> tuple[str, ...]:
        """The section's blank-line-separated paragraphs, each one memory item.

        A bullet list is kept whole: its items are one thought, and splitting a list into
        five unrelated directives loses the thing that made it a list.
        """
        chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", self.body)]
        return tuple(chunk for chunk in chunks if chunk)


@dataclass(frozen=True)
class KnowledgeDocument:
    path: Path
    title: str
    sections: tuple[KnowledgeSection, ...]
    domains: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    strategy: MemoryStrategy = MemoryStrategy.AUTO
    split_level: int = 2


@dataclass
class KnowledgeReport:
    documents: int = 0
    items: int = 0
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.removed)

    def summary_lines(self) -> list[str]:
        lines = [
            f"documents         : {self.documents}",
            f"memory items      : {self.items}",
            f"created           : {len(self.created)}",
            f"updated           : {len(self.updated)}",
            f"removed           : {len(self.removed)}",
            f"unchanged         : {len(self.unchanged)}",
        ]
        for label, ids in (("created", self.created), ("updated", self.updated), ("removed", self.removed)):
            for identifier in ids[:10]:
                lines.append(f"  {label}: {identifier}")
        return lines


# --- parsing ------------------------------------------------------------------

_FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)


def slugify(text: str) -> str:
    """Reduce to `[a-z0-9_]`, so an id is greppable and safe as a filename."""
    lowered = re.sub(r"[^a-z0-9]+", "_", text.strip().lower())
    return lowered.strip("_")


def _parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONT_MATTER_RE.match(text)
    if match is None:
        return {}, text

    raw = yaml.safe_load(match.group(1)) or {}
    if not isinstance(raw, dict):
        raise KnowledgeError("front matter must be a mapping")

    unknown = sorted(set(raw) - _FRONT_MATTER_KEYS)
    if unknown:
        raise KnowledgeError(
            f"unknown front-matter key(s) {', '.join(repr(k) for k in unknown)}. "
            f"Allowed: {', '.join(sorted(_FRONT_MATTER_KEYS))}. A typo must not silently "
            "mean 'no domains'."
        )
    return raw, text[match.end() :]


def _split_sections(body: str, level: int) -> tuple[str | None, list[KnowledgeSection]]:
    """`(document title, sections)`. Splits on headings of exactly ``level``."""
    lines = body.splitlines()
    title: str | None = None
    sections: list[KnowledgeSection] = []

    current_heading: str | None = None
    current: list[str] = []
    preamble: list[str] = []
    marker = "#" * level + " "
    in_fence = False

    def flush() -> None:
        if current_heading is not None:
            sections.append(
                KnowledgeSection(
                    heading=current_heading, body="\n".join(current).strip(), level=level
                )
            )

    for line in lines:
        stripped = line.strip()
        # A `##` inside a fenced code block is code, not a heading.
        if stripped.startswith("```"):
            in_fence = not in_fence

        if not in_fence and title is None and stripped.startswith("# ") and level > 1:
            title = stripped[2:].strip()
            continue

        if not in_fence and stripped.startswith(marker):
            flush()
            current_heading = stripped[len(marker) :].strip()
            current = []
            continue

        if current_heading is None:
            preamble.append(line)
        else:
            current.append(line)

    flush()

    if not sections:
        # No heading at the split level: the whole document is one item. Better than
        # emitting nothing and leaving the author wondering where their content went.
        text = "\n".join(preamble).strip()
        if text:
            sections.append(KnowledgeSection(heading=title or "", body=text, level=level))

    return title, sections


def parse_document(path: Path) -> KnowledgeDocument:
    """Parse one Markdown file into a document plus its sections."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")

    try:
        front_matter, body = _parse_front_matter(text)
    except KnowledgeError as error:
        raise KnowledgeError(f"{path}: {error}") from error

    raw_strategy = str(front_matter.get("strategy", MemoryStrategy.AUTO.value)).upper()
    try:
        strategy = MemoryStrategy(raw_strategy)
    except ValueError as error:
        supported = ", ".join(s.value for s in MemoryStrategy)
        raise KnowledgeError(
            f"{path}: strategy {raw_strategy!r} is not one of {supported}"
        ) from error

    split_level = int(front_matter.get("split_level", 2))
    if not 1 <= split_level <= 6:
        raise KnowledgeError(f"{path}: split_level must be between 1 and 6")

    title, sections = _split_sections(body, split_level)

    if not sections:
        raise KnowledgeError(f"{path}: contains no content to compile")

    for section in sections:
        for paragraph in section.paragraphs():
            if len(paragraph) > MAX_INSTRUCTION_CHARS:
                opening = " ".join(paragraph.split()[:8])
                raise KnowledgeError(
                    f"{path}: in section {section.heading or '(untitled)'!r}, the paragraph "
                    f"starting {opening!r} is {len(paragraph)} characters. The API caps a "
                    f"memory item's instruction at {MAX_INSTRUCTION_CHARS}. Split it into "
                    "shorter statements — each one becomes its own retrievable item."
                )

    headings = [section.heading for section in sections]
    duplicates = sorted({h for h in headings if headings.count(h) > 1})
    if duplicates:
        raise KnowledgeError(
            f"{path}: duplicate heading(s) {', '.join(duplicates)} — ids are derived from "
            "headings, so one would silently overwrite the other"
        )

    return KnowledgeDocument(
        path=path,
        title=title or path.stem.replace("_", " ").replace("-", " ").title(),
        sections=tuple(sections),
        domains=tuple(sorted(str(d) for d in front_matter.get("domains", []) or [])),
        keywords=tuple(sorted(str(k) for k in front_matter.get("keywords", []) or [])),
        strategy=strategy,
        split_level=split_level,
    )


def derive_keywords(heading: str, explicit: tuple[str, ...]) -> tuple[str, ...]:
    """Heading terms plus whatever the author named. Derived ones are a default, not the rule."""
    terms = {
        word
        for word in re.split(r"[^a-z0-9]+", heading.lower())
        if word and word not in _STOP_WORDS and len(word) > 1
    }
    return tuple(sorted(terms | {k.lower() for k in explicit}))


def item_id(
    document: KnowledgeDocument,
    section: KnowledgeSection,
    index: int = 0,
    total: int = 1,
) -> str:
    """`<file-stem>_<heading-slug>`, plus a two-digit suffix when a section has several.

    Index-based rather than content-based so that fixing a typo shows up as an *update*
    rather than as a remove plus a create. The cost is that inserting a paragraph shifts the
    ids after it; sections are short and insertions are rarer than edits.
    """
    stem = slugify(document.path.stem)
    heading = slugify(section.heading)
    base = f"{stem}_{heading}" if heading else stem
    return base if total == 1 else f"{base}_{index + 1:02d}"


# --- compiling ----------------------------------------------------------------


def compile_documents(paths: list[Path]) -> list[Any]:
    """Compile every document into memory items, sorted by id."""
    from gooddata_sdk.catalog.workspace.declarative_model.workspace.analytics_model.analytics_model import (  # noqa: E501
        CatalogDeclarativeMemoryItem,
    )

    items: dict[str, Any] = {}
    for path in sorted(paths):
        document = parse_document(path)
        for section in document.sections:
            paragraphs = section.paragraphs()
            for index, paragraph in enumerate(paragraphs):
                identifier = item_id(document, section, index, len(paragraphs))
                if identifier in items:
                    raise KnowledgeError(
                        f"{path}: id {identifier!r} collides with another document's section"
                    )
                tags = [OWNER_TAG] + (
                    [f"{DOMAIN_TAG_PREFIX}{d}" for d in document.domains]
                    if document.domains
                    else [SHARED_TAG]
                )
                # description carries provenance (10000 chars available), so someone reading
                # the item in the org can find the Markdown that produced it.
                description = (
                    f"{document.title} › {section.heading}" if section.heading else document.title
                )
                items[identifier] = CatalogDeclarativeMemoryItem(
                    id=identifier,
                    title=(section.heading or document.title)[:MAX_INSTRUCTION_CHARS],
                    instruction=paragraph,
                    description=f"{description} (compiled from {path.as_posix()})"[
                        :MAX_DESCRIPTION_CHARS
                    ],
                    strategy=document.strategy.value,
                    keywords=list(derive_keywords(section.heading, document.keywords)),
                    tags=sorted(tags),
                )
    return [items[key] for key in sorted(items)]


def source_documents(source_dir: Path) -> list[Path]:
    return sorted(Path(source_dir).glob("*.md"))


# --- reconciliation -----------------------------------------------------------


def _is_owned(item: Any) -> bool:
    return OWNER_TAG in (getattr(item, "tags", None) or [])


def _comparable(item: Any) -> tuple[Any, ...]:
    return (
        str(item.id),
        getattr(item, "title", None),
        getattr(item, "instruction", None),
        getattr(item, "description", None),
        getattr(item, "strategy", None),
        tuple(getattr(item, "keywords", None) or []),
        tuple(getattr(item, "tags", None) or []),
    )


def apply_to_tree(model: Any, items: list[Any]) -> KnowledgeReport:
    """Replace exactly the owned set. Anything untagged is left alone.

    This is the function that must not be positional. A build that owned every memory item
    in the channel would delete a captured or hand-authored one the first time it ran.
    """
    analytics = model.analytics
    existing = list(getattr(analytics, "memory_items", None) or [])

    owned_before = {str(item.id): item for item in existing if _is_owned(item)}
    foreign = [item for item in existing if not _is_owned(item)]
    compiled = {str(item.id): item for item in items}

    report = KnowledgeReport(items=len(compiled))
    for identifier, item in sorted(compiled.items()):
        previous = owned_before.get(identifier)
        if previous is None:
            report.created.append(identifier)
        elif _comparable(previous) != _comparable(item):
            report.updated.append(identifier)
        else:
            report.unchanged.append(identifier)
    report.removed = sorted(set(owned_before) - set(compiled))

    analytics.memory_items = sorted(
        [*foreign, *compiled.values()], key=lambda item: str(item.id)
    )
    return report


def build_knowledge(
    *,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    layout_path: Path = Path("layouts/workspaces/globalmart"),
    check: bool = False,
) -> KnowledgeReport:
    """Compile the documents into the layout tree. Writes nothing under ``check``."""
    from globalmart.layout_io import read_tree, write_tree

    source_dir = Path(source_dir)
    if not source_dir.exists():
        raise KnowledgeError(f"No knowledge source directory at {source_dir}")

    paths = source_documents(source_dir)
    model = read_tree(Path(layout_path))

    items = compile_documents(paths)
    report = apply_to_tree(model, items)
    report.documents = len(paths)

    if not check:
        write_tree(model, Path(layout_path))

    return report
