"""The authored documentation corpus: parse it, validate it, name it.

FEAT-008 compiles Markdown paragraphs into AI *memory items* — standing directives, capped
at 255 characters. This is the other channel: whole documents, published to AI Knowledge,
which explain the workspace rather than instruct the assistant about it. The two are
siblings. A fact belongs in exactly one of them, and `knowledge.py`'s docstring carries the
same split from the other side.

**The API chunks; we do not.** `PUT .../knowledge/documents` returns `numChunks`, so chunk
boundaries are the server's business and are not observable here. What is ours is the shape
of the prose that gets chunked, and the retrieval research is unambiguous about it:
header-based splitting is the strongest default for Markdown, and quality falls off once a
section stops being self-contained. So this module enforces authoring discipline —
one subject per document, `##` sections that each carry one idea, and ceilings that fail the
build rather than degrading retrieval silently — and asserts nothing whatsoever about
`numChunks`.

**The directory tree is the review surface; the filename is the API's identity.** A document
at `docs/knowledge-corpus/reference/net-revenue.md` publishes as
`gm-corpus__reference__net-revenue.md`. The prefix is how reconciliation recognises its own
work in an org it shares with hand-uploaded files (`knowledge_docs.py`), and
`published_filename` is the single place that mapping exists.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

from globalmart.config import GlobalmartError

DEFAULT_CORPUS_DIR = Path("docs/knowledge-corpus")
DEFAULT_MANIFEST = Path("config/corpus.yaml")
DEFAULT_QUESTIONS = Path("config/corpus-questions.yaml")

#: Ownership marker #1. Carried in the published filename because filename is the document's
#: identity in this API — `PUT` upserts by it, and a listing always returns it. `scopes` is
#: marker #2 and lives in `knowledge_docs.py`; see `RemoteDocument.is_ours`.
FILENAME_PREFIX = "gm-corpus__"

#: Roughly the 2,500-token context cliff the chunking research reports, in characters. A
#: section past this has stopped being one idea, whatever its author believes.
MAX_SECTION_CHARS = 3_000

#: A whole document past this is a topic group pretending to be a document. Split it.
MAX_DOCUMENT_CHARS = 24_000

#: A heading with one line under it is a heading, not a chunk: it retrieves as a fragment
#: with no context. Either give it content or fold it into its neighbour.
MIN_SECTION_CHARS = 120

_FRONT_MATTER_KEYS = frozenset(
    {"kind", "title", "scope", "owner", "domains", "covers", "anchor"}
)
_COVERS_KEYS = frozenset({"metrics", "datasets", "visualizations", "dashboards"})
_REQUIRED_KEYS = ("kind", "title", "scope", "owner")

_FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)


class CorpusError(GlobalmartError):
    """A corpus document cannot be parsed, or violates the authoring contract."""


class DiataxisKind(StrEnum):
    """Diátaxis: every document is exactly one of these, and says which.

    The point of naming it in front matter rather than inferring it from the directory is
    that the *author* has to decide. A document that cannot answer "which one am I" is the
    document that mixes a reference table into a rationale and retrieves badly for both.
    """

    TUTORIAL = "tutorial"
    HOW_TO = "how_to"
    REFERENCE = "reference"
    EXPLANATION = "explanation"


@dataclass(frozen=True)
class CorpusSection:
    """One `##`/`###` section: the unit the author controls and the server chunks."""

    heading: str
    level: int
    body: str

    @property
    def char_count(self) -> int:
        return len(self.body)


@dataclass(frozen=True)
class CoversSelection:
    """Which layout objects a document documents. Ids or `fnmatch` patterns.

    A pattern that matches nothing is fatal in `corpus_coverage.py` — that is the case where
    a metric was renamed and its document was not, which is precisely the drift this feature
    exists to catch.
    """

    metrics: tuple[str, ...] = ()
    datasets: tuple[str, ...] = ()
    visualizations: tuple[str, ...] = ()
    dashboards: tuple[str, ...] = ()

    def patterns(self, kind: str) -> tuple[str, ...]:
        value: tuple[str, ...] = getattr(self, kind)
        return value

    def is_empty(self) -> bool:
        return not (self.metrics or self.datasets or self.visualizations or self.dashboards)


@dataclass(frozen=True)
class CorpusDocument:
    """One authored document, parsed and validated."""

    path: Path
    kind: DiataxisKind
    title: str
    scope: str
    owner: str
    body: str
    sections: tuple[CorpusSection, ...]
    domains: tuple[str, ...] = ()
    covers: CoversSelection = field(default_factory=CoversSelection)
    anchor: bool = False

    @property
    def filename(self) -> str:
        return published_filename(self.path, self.kind)

    @property
    def digest(self) -> str:
        """sha256 of the published bytes.

        Idempotency without local state: the org's raw download of this filename either
        digests to this or it does not. `compare.py` does the same thing for layouts, except
        that a layout comes back normalized by the server and a file comes back verbatim, so
        there is no server-owned-field problem to work around here.
        """
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()

    @property
    def char_count(self) -> int:
        return len(self.body)

    def scopes(self) -> tuple[str, ...]:
        """The `scopes` this document is published with.

        Diátaxis kind and topic group travel as scopes so the assistant's knowledge search
        can be narrowed the same way a reader narrows by directory. `domain/<key>` entries
        are how per-domain grouping is expressed on this channel — see CONTRACT.md on why
        `AiSelection.knowledge_ids` is *not* the mechanism.
        """
        from globalmart.knowledge_docs import OWNER_SCOPE

        return tuple(
            [OWNER_SCOPE, f"kind/{self.kind.value}", f"scope/{self.scope}"]
            + [f"domain/{key}" for key in self.domains]
        )


@dataclass
class CorpusBuildReport:
    """What `knowledge-docs build` prints."""

    documents: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    by_scope: dict[str, int] = field(default_factory=dict)
    total_chars: int = 0
    largest: tuple[str, int] = ("", 0)
    anchors: tuple[str, ...] = ()

    def summary_lines(self) -> list[str]:
        lines = [
            f"documents         : {self.documents}",
            f"total characters  : {self.total_chars:,}",
            f"largest document  : {self.largest[0]} ({self.largest[1]:,} chars)",
            f"anchored documents: {len(self.anchors)}",
        ]
        lines.append("by kind:")
        lines.extend(f"  {kind:14s} {count}" for kind, count in sorted(self.by_kind.items()))
        lines.append("by scope:")
        lines.extend(f"  {scope:14s} {count}" for scope, count in sorted(self.by_scope.items()))
        return lines


# --- naming -------------------------------------------------------------------


def slugify(text: str) -> str:
    """Reduce to `[a-z0-9-]`, so a filename is greppable and URL-safe."""
    lowered = re.sub(r"[^a-z0-9]+", "-", text.strip().lower())
    return lowered.strip("-")


def published_filename(path: Path, kind: DiataxisKind) -> str:
    """`gm-corpus__<kind>__<slug>.md` — the document's identity in the API.

    The kind is in the name rather than only in `scopes` so that a listing is readable
    without cross-referencing, and so two documents with the same stem under different kinds
    do not collide.
    """
    return f"{FILENAME_PREFIX}{kind.value}__{slugify(Path(path).stem)}.md"


# --- parsing ------------------------------------------------------------------


def _parse_front_matter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    match = _FRONT_MATTER_RE.match(text)
    if match is None:
        raise CorpusError(
            f"{path}: no front matter. Every corpus document declares at least "
            f"{', '.join(_REQUIRED_KEYS)} — a document nobody owns is a document nobody fixes."
        )

    raw = yaml.safe_load(match.group(1)) or {}
    if not isinstance(raw, dict):
        raise CorpusError(f"{path}: front matter must be a mapping")

    unknown = sorted(set(raw) - _FRONT_MATTER_KEYS)
    if unknown:
        raise CorpusError(
            f"{path}: unknown front-matter key(s) {', '.join(repr(k) for k in unknown)}. "
            f"Allowed: {', '.join(sorted(_FRONT_MATTER_KEYS))}. A typo must not silently mean "
            "'documents nothing'."
        )

    for key in _REQUIRED_KEYS:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise CorpusError(
                f"{path}: front-matter key {key!r} is required and must be a non-empty string"
            )

    return raw, text[match.end() :]


def _parse_covers(node: Any, path: Path) -> CoversSelection:
    if node is None:
        return CoversSelection()
    if not isinstance(node, dict):
        raise CorpusError(f"{path}: covers: must be a mapping of object kind to id list")

    unknown = sorted(set(node) - _COVERS_KEYS)
    if unknown:
        raise CorpusError(
            f"{path}: covers: has unknown key(s) {', '.join(repr(k) for k in unknown)}. "
            f"Allowed: {', '.join(sorted(_COVERS_KEYS))}."
        )

    def ids(key: str) -> tuple[str, ...]:
        value = node.get(key) or []
        if isinstance(value, str):
            raise CorpusError(f"{path}: covers.{key} must be a list, not a single string")
        return tuple(sorted(str(item) for item in value))

    return CoversSelection(
        metrics=ids("metrics"),
        datasets=ids("datasets"),
        visualizations=ids("visualizations"),
        dashboards=ids("dashboards"),
    )


def _split_sections(body: str, path: Path) -> tuple[CorpusSection, ...]:
    """Split on `##` and `###`, rejecting a second `#`.

    A fenced code block is code: `## not a heading` inside triple backticks is content. That
    is the same guard `knowledge.py` carries, re-asserted here rather than inherited, because
    a corpus document is far more likely to contain fenced Markdown examples than a memory
    item is.
    """
    sections: list[CorpusSection] = []
    heading: str | None = None
    level = 2
    current: list[str] = []
    seen_title = False
    in_fence = False

    def flush() -> None:
        if heading is not None:
            sections.append(
                CorpusSection(heading=heading, level=level, body="\n".join(current).strip())
            )

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence

        if not in_fence and stripped.startswith("# "):
            if seen_title:
                raise CorpusError(
                    f"{path}: a second top-level '# ' heading ({stripped[2:].strip()!r}). One "
                    "document is one subject; a second title means this is two documents."
                )
            seen_title = True
            continue

        if not in_fence and (stripped.startswith("## ") or stripped.startswith("### ")):
            flush()
            level = 3 if stripped.startswith("### ") else 2
            heading = stripped.lstrip("#").strip()
            current = []
            continue

        if heading is not None:
            current.append(line)

    flush()
    return tuple(sections)


def parse_corpus_document(path: Path) -> CorpusDocument:
    """Parse and validate one document. Raises rather than warning."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    front_matter, body = _parse_front_matter(text, path)

    raw_kind = str(front_matter["kind"]).strip().lower()
    try:
        kind = DiataxisKind(raw_kind)
    except ValueError as error:
        valid = ", ".join(k.value for k in DiataxisKind)
        raise CorpusError(
            f"{path}: kind {raw_kind!r} is not a Diátaxis kind. One of: {valid}."
        ) from error

    body = body.strip() + "\n"
    sections = _split_sections(body, path)

    if not sections:
        raise CorpusError(
            f"{path}: no '##' sections. Header-based sections are what the retrieval layer "
            "chunks on, so a document without them retrieves as one undifferentiated blob."
        )

    if len(body) > MAX_DOCUMENT_CHARS:
        raise CorpusError(
            f"{path}: {len(body):,} characters exceeds the {MAX_DOCUMENT_CHARS:,} ceiling. "
            "Split it by subject — a document this long is a topic group."
        )

    headings = [section.heading for section in sections]
    duplicates = sorted({h for h in headings if headings.count(h) > 1})
    if duplicates:
        raise CorpusError(
            f"{path}: duplicate heading(s) {', '.join(duplicates)}. A retrieved chunk is "
            "identified by its heading, so two identical ones are indistinguishable to a reader."
        )

    for section in sections:
        if section.char_count > MAX_SECTION_CHARS:
            raise CorpusError(
                f"{path}: section {section.heading!r} is {section.char_count:,} characters, over "
                f"the {MAX_SECTION_CHARS:,} ceiling. A section past this has stopped being one "
                "idea; give it sub-headings or split the document."
            )
        if section.char_count < MIN_SECTION_CHARS:
            raise CorpusError(
                f"{path}: section {section.heading!r} is only {section.char_count} characters "
                f"(minimum {MIN_SECTION_CHARS}). It retrieves as a fragment with no context — "
                "give it content or fold it into its neighbour."
            )

    return CorpusDocument(
        path=path,
        kind=kind,
        title=str(front_matter["title"]).strip(),
        scope=str(front_matter["scope"]).strip(),
        owner=str(front_matter["owner"]).strip(),
        body=body,
        sections=sections,
        domains=tuple(sorted(str(d) for d in (front_matter.get("domains") or []))),
        covers=_parse_covers(front_matter.get("covers"), path),
        anchor=bool(front_matter.get("anchor", False)),
    )


def corpus_paths(corpus_dir: Path = DEFAULT_CORPUS_DIR) -> list[Path]:
    """Every `.md` under the corpus tree, in a stable order."""
    return sorted(Path(corpus_dir).rglob("*.md"))


def load_corpus(corpus_dir: Path = DEFAULT_CORPUS_DIR) -> list[CorpusDocument]:
    """Parse every document, and reject a published-filename collision.

    Two source paths that publish to one filename would silently overwrite each other on
    upsert — the API's identity is the filename, not the path — so the collision is caught
    here, naming both files.
    """
    corpus_dir = Path(corpus_dir)
    if not corpus_dir.exists():
        raise CorpusError(f"No corpus directory at {corpus_dir}")

    documents: list[CorpusDocument] = []
    by_filename: dict[str, Path] = {}
    for path in corpus_paths(corpus_dir):
        document = parse_corpus_document(path)
        previous = by_filename.get(document.filename)
        if previous is not None:
            raise CorpusError(
                f"{path} and {previous} both publish as {document.filename!r}. Filename is the "
                "API's identity, so one would overwrite the other on upsert."
            )
        by_filename[document.filename] = path
        documents.append(document)

    if not documents:
        raise CorpusError(f"{corpus_dir} holds no .md documents")
    return documents


def build_report(documents: list[CorpusDocument]) -> CorpusBuildReport:
    """Summarise a parsed corpus. Everything fatal has already raised by here."""
    report = CorpusBuildReport(documents=len(documents))
    for document in documents:
        report.by_kind[document.kind.value] = report.by_kind.get(document.kind.value, 0) + 1
        report.by_scope[document.scope] = report.by_scope.get(document.scope, 0) + 1
        report.total_chars += document.char_count
        if document.char_count > report.largest[1]:
            report.largest = (document.filename, document.char_count)
    report.anchors = tuple(sorted(d.filename for d in documents if d.anchor))
    return report


def matches(pattern: str, identifier: str) -> bool:
    """`fnmatch`, so `m_revenue_*` covers a family without listing it."""
    return fnmatch(identifier, pattern)
