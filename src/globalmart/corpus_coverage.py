"""Is everything in the workspace documented, or deliberately not?

The docs-as-code tooling generation treats documentation rot as a clock: front matter
carries a review date, and CI complains after some horizon. That is the best available check
when the subject of the documentation is prose. Here the subject is a machine-readable
workspace, so a stronger one exists — compare the corpus against the layout and name every
object that nobody documented.

Three ways an object is accounted for, and no fourth:

1. **documented** — some corpus document's ``covers:`` names it, by id or by pattern;
2. **excluded** — ``config/corpus.yaml`` names it *with a reason*;
3. nothing, which is ``uncovered`` and fatal.

That is `coverage.py`'s shape, deliberately: the same three-way split, the same
report-then-``raise_for`` pair, the same ``--strict`` rule about placeholder reasons, and the
same imported ``PLACEHOLDER_REASONS`` so "TODO" cannot become a documented exclusion in one
module and not the other. What it is *not* is an extension of `CoverageReport`, which is
keyed by dashboards, visualizations and AI objects and belongs to FEAT-003.

Two symmetrical failures are both fatal, and the second is the one that catches real drift:

- a ``covers:`` pattern that matches nothing — a metric was renamed and its document was not;
- a manifest exclusion that matches nothing — an object was deleted and its excuse outlived it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.config import GlobalmartError
from globalmart.corpus import DEFAULT_MANIFEST, CorpusDocument, matches
from globalmart.domains import PLACEHOLDER_REASONS

#: The object classes a document can claim to cover, in report order.
OBJECT_CLASSES: tuple[str, ...] = ("datasets", "metrics", "visualizations", "dashboards")

_MANIFEST_KEYS = frozenset({"version", "parent_workspace_id", "exclusions"})


class CorpusManifestError(GlobalmartError):
    """``config/corpus.yaml`` is malformed, or an exclusion has no reason."""


class CorpusCoverageError(GlobalmartError):
    """Something in the workspace is documented nowhere, or a pattern is stale."""

    def __init__(self, message: str, report: CorpusCoverageReport) -> None:
        super().__init__(message)
        self.report = report


@dataclass(frozen=True)
class CorpusExclusion:
    """One deliberate omission. An id or an ``fnmatch`` pattern, plus a sentence."""

    id: str
    reason: str

    def reason_is_placeholder(self) -> bool:
        """Same rule as ``domains.Exclusion`` — imported, never re-derived."""
        stripped = self.reason.strip()
        if not stripped:
            return True
        return stripped.lower() in PLACEHOLDER_REASONS


@dataclass(frozen=True)
class CorpusManifest:
    version: int
    parent_workspace_id: str
    datasets: tuple[CorpusExclusion, ...] = ()
    metrics: tuple[CorpusExclusion, ...] = ()
    visualizations: tuple[CorpusExclusion, ...] = ()
    dashboards: tuple[CorpusExclusion, ...] = ()
    path: Path | None = None

    def exclusions(self, object_class: str) -> tuple[CorpusExclusion, ...]:
        value: tuple[CorpusExclusion, ...] = getattr(self, object_class)
        return value


@dataclass(frozen=True)
class ClassCoverage:
    """One object class: what is documented, what is excused, what is neither."""

    total: int = 0
    documented: dict[str, tuple[str, ...]] = field(default_factory=dict)
    excluded: dict[str, str] = field(default_factory=dict)
    uncovered: tuple[str, ...] = ()

    @property
    def covered(self) -> int:
        return len(self.documented) + len(self.excluded)


@dataclass
class CorpusCoverageReport:
    by_class: dict[str, ClassCoverage] = field(default_factory=dict)
    #: A `covers:` id or pattern that matches nothing in the workspace -> the document.
    unknown_covers: dict[str, str] = field(default_factory=dict)
    #: A manifest exclusion that matches nothing -> its dotted manifest path.
    unmatched_exclusions: dict[str, str] = field(default_factory=dict)
    placeholder_reasons: dict[str, str] = field(default_factory=dict)
    documents: int = 0
    #: Documents whose `covers:` is empty. Legitimate — a tutorial documents no single
    #: object — so this is reported, never fatal.
    documents_covering_nothing: tuple[str, ...] = ()

    def uncovered_total(self) -> int:
        return sum(len(cov.uncovered) for cov in self.by_class.values())

    def is_clean(self, *, strict: bool = False) -> bool:
        if self.uncovered_total() or self.unknown_covers or self.unmatched_exclusions:
            return False
        return not (strict and self.placeholder_reasons)

    def as_dict(self) -> dict[str, Any]:
        return {
            "documents": self.documents,
            "by_class": {
                name: {
                    "total": cov.total,
                    "documented": {k: list(v) for k, v in cov.documented.items()},
                    "excluded": dict(cov.excluded),
                    "uncovered": list(cov.uncovered),
                }
                for name, cov in self.by_class.items()
            },
            "unknown_covers": dict(self.unknown_covers),
            "unmatched_exclusions": dict(self.unmatched_exclusions),
            "placeholder_reasons": dict(self.placeholder_reasons),
            "documents_covering_nothing": list(self.documents_covering_nothing),
        }

    def summary_lines(self) -> list[str]:
        lines = [f"documents         : {self.documents}"]
        for name in OBJECT_CLASSES:
            cov = self.by_class.get(name)
            if cov is None:
                continue
            lines.append(
                f"{name:18s}: {cov.covered}/{cov.total} accounted for "
                f"({len(cov.documented)} documented, {len(cov.excluded)} excluded, "
                f"{len(cov.uncovered)} UNCOVERED)"
            )
        if self.unknown_covers:
            lines.append(f"stale covers:     : {len(self.unknown_covers)}")
        if self.unmatched_exclusions:
            lines.append(f"stale exclusions  : {len(self.unmatched_exclusions)}")
        if self.placeholder_reasons:
            lines.append(f"placeholder reasons: {len(self.placeholder_reasons)}")
        return lines

    def table_lines(self) -> list[str]:
        header = f"{'class':18s} {'total':>7s} {'documented':>11s} {'excluded':>9s} {'uncovered':>10s}"
        lines = [header, "-" * len(header)]
        for name in OBJECT_CLASSES:
            cov = self.by_class.get(name)
            if cov is None:
                continue
            lines.append(
                f"{name:18s} {cov.total:7d} {len(cov.documented):11d} "
                f"{len(cov.excluded):9d} {len(cov.uncovered):10d}"
            )
        return lines


# --- the manifest -------------------------------------------------------------


def _exclusions(node: Any, path: str) -> tuple[CorpusExclusion, ...]:
    if node is None:
        return ()
    if not isinstance(node, list):
        raise CorpusManifestError(f"{path}: must be a list of {{id, reason}} mappings")

    out: list[CorpusExclusion] = []
    for index, entry in enumerate(node):
        where = f"{path}[{index}]"
        if not isinstance(entry, dict):
            raise CorpusManifestError(f"{where}: must be a mapping with 'id' and 'reason'")
        unknown = sorted(set(entry) - {"id", "reason"})
        if unknown:
            raise CorpusManifestError(
                f"{where}: unknown key(s) {', '.join(repr(k) for k in unknown)}. "
                "Allowed: id, reason."
            )
        identifier = entry.get("id")
        reason = entry.get("reason")
        if not isinstance(identifier, str) or not identifier.strip():
            raise CorpusManifestError(f"{where}: 'id' is required and must be a non-empty string")
        if not isinstance(reason, str) or not reason.strip():
            raise CorpusManifestError(
                f"{where}: exclusion {identifier!r} has no reason. An exclusion costs a "
                "sentence; the absence of one is how an undocumented object goes unnoticed."
            )
        out.append(CorpusExclusion(id=identifier.strip(), reason=reason.strip()))
    return tuple(out)


def load_corpus_manifest(path: Path = DEFAULT_MANIFEST) -> CorpusManifest:
    """Strict loader, modelled on ``domains.load_domains``: an unknown key raises.

    A missing file is not an error — a corpus with nothing excluded is the goal state, and
    requiring an empty file to say so would be ceremony.
    """
    path = Path(path)
    if not path.exists():
        return CorpusManifest(version=1, parent_workspace_id="globalmart", path=None)

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise CorpusManifestError(f"{path}: the manifest must be a mapping")

    unknown = sorted(set(raw) - _MANIFEST_KEYS)
    if unknown:
        raise CorpusManifestError(
            f"{path}: unknown key(s) {', '.join(repr(k) for k in unknown)}. "
            f"Allowed: {', '.join(sorted(_MANIFEST_KEYS))}."
        )

    exclusions = raw.get("exclusions") or {}
    if not isinstance(exclusions, dict):
        raise CorpusManifestError(f"{path}: exclusions: must be a mapping of object class to list")
    unknown_classes = sorted(set(exclusions) - set(OBJECT_CLASSES))
    if unknown_classes:
        raise CorpusManifestError(
            f"{path}: exclusions has unknown class(es) "
            f"{', '.join(repr(k) for k in unknown_classes)}. "
            f"Allowed: {', '.join(OBJECT_CLASSES)}."
        )

    return CorpusManifest(
        version=int(raw.get("version", 1)),
        parent_workspace_id=str(raw.get("parent_workspace_id", "globalmart")),
        datasets=_exclusions(exclusions.get("datasets"), "exclusions.datasets"),
        metrics=_exclusions(exclusions.get("metrics"), "exclusions.metrics"),
        visualizations=_exclusions(exclusions.get("visualizations"), "exclusions.visualizations"),
        dashboards=_exclusions(exclusions.get("dashboards"), "exclusions.dashboards"),
        path=path,
    )


# --- the check ----------------------------------------------------------------


def _ids(container: Any, attribute: str) -> set[str]:
    return {str(obj.id) for obj in (getattr(container, attribute, None) or [])}


def workspace_census(model: CatalogDeclarativeWorkspaceModel) -> dict[str, set[str]]:
    """Every object this feature can be asked to document, by class."""
    return {
        "datasets": _ids(model.ldm, "datasets") | _ids(model.ldm, "date_instances"),
        "metrics": _ids(model.analytics, "metrics"),
        "visualizations": _ids(model.analytics, "visualization_objects"),
        "dashboards": _ids(model.analytics, "analytical_dashboards"),
    }


def check_corpus_coverage(
    model: CatalogDeclarativeWorkspaceModel,
    documents: list[CorpusDocument],
    manifest: CorpusManifest,
) -> CorpusCoverageReport:
    """Classify every object in the parent as documented, excluded, or uncovered."""
    report = CorpusCoverageReport(documents=len(documents))
    census = workspace_census(model)

    report.documents_covering_nothing = tuple(
        sorted(document.filename for document in documents if document.covers.is_empty())
    )

    for object_class in OBJECT_CLASSES:
        known = census[object_class]

        documented: dict[str, set[str]] = {}
        for document in documents:
            for pattern in document.covers.patterns(object_class):
                hits = {identifier for identifier in known if matches(pattern, identifier)}
                if not hits:
                    # Fatal, and the single most useful check here: this is a rename that
                    # left its document behind.
                    report.unknown_covers.setdefault(
                        f"{object_class}:{pattern}", document.path.as_posix()
                    )
                    continue
                for identifier in hits:
                    documented.setdefault(identifier, set()).add(document.filename)

        excluded: dict[str, str] = {}
        for index, exclusion in enumerate(manifest.exclusions(object_class)):
            where = f"exclusions.{object_class}[{index}]"
            hits = {identifier for identifier in known if matches(exclusion.id, identifier)}
            if not hits:
                report.unmatched_exclusions.setdefault(f"{object_class}:{exclusion.id}", where)
                continue
            for identifier in hits:
                excluded.setdefault(identifier, exclusion.reason)
            if exclusion.reason_is_placeholder():
                report.placeholder_reasons[f"{object_class}:{exclusion.id}"] = exclusion.reason

        # Documentation wins over exclusion: an object that is both documented and excused is
        # documented, and the stale excuse shows up as nothing at all. That is deliberate —
        # the alternative is failing a build for having written too much.
        excluded = {k: v for k, v in excluded.items() if k not in documented}

        report.by_class[object_class] = ClassCoverage(
            total=len(known),
            documented={k: tuple(sorted(v)) for k, v in sorted(documented.items())},
            excluded=dict(sorted(excluded.items())),
            uncovered=tuple(sorted(known - set(documented) - set(excluded))),
        )

    return report


def raise_for_corpus_report(report: CorpusCoverageReport, *, strict: bool = False) -> None:
    """Turn an unclean report into a loud failure, naming what to do about it."""
    problems: list[str] = []

    for object_class in OBJECT_CLASSES:
        cov = report.by_class.get(object_class)
        if cov is None or not cov.uncovered:
            continue
        shown = "\n    ".join(cov.uncovered[:40])
        more = "" if len(cov.uncovered) <= 40 else f"\n    ... and {len(cov.uncovered) - 40} more"
        problems.append(
            f"{len(cov.uncovered)} {object_class[:-1]}(s) are documented by no corpus document "
            f"and excluded by no manifest entry:\n    {shown}{more}"
        )

    if report.unknown_covers:
        listed = "\n    ".join(
            f"{pattern}  (in {source})" for pattern, source in report.unknown_covers.items()
        )
        problems.append(
            f"{len(report.unknown_covers)} covers: pattern(s) match nothing in the workspace. "
            f"An object was renamed or deleted and its documentation was not:\n    {listed}"
        )

    if report.unmatched_exclusions:
        listed = "\n    ".join(
            f"{pattern}  ({where})" for pattern, where in report.unmatched_exclusions.items()
        )
        problems.append(
            f"{len(report.unmatched_exclusions)} manifest exclusion(s) match nothing. The "
            f"object is gone and its excuse outlived it:\n    {listed}"
        )

    if strict and report.placeholder_reasons:
        listed = "\n    ".join(
            f"{pattern}: {reason!r}" for pattern, reason in report.placeholder_reasons.items()
        )
        problems.append(
            f"{len(report.placeholder_reasons)} exclusion(s) carry a placeholder reason. A "
            f"deliberate omission must be justified in words:\n    {listed}"
        )

    if problems:
        raise CorpusCoverageError("\n\n".join(problems), report)
