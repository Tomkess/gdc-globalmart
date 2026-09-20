"""Per-domain filtering of the AI channels.

The predecessor copied `memoryItems` and `parameters` verbatim into all twelve children, so
every child carried every other domain's AI memory. STEERING names that outcome directly:
"cross-domain AI memory in a child is also a defect".

Deny-by-default, as FEAT-003's manifest defines it: an AI object reaches a child only when
that domain names its id, one of the domain's `memory_item_tags` matches it, or the
manifest's `shared.ai` declares it. Nothing is inherited.

A selected id that does not exist in the parent fails the run — an id list that has drifted
away from the content is the quiet way a domain ends up with no AI context at all. A
`memory_item_tags` entry matching nothing is reported rather than fatal: a tag is a standing
rule about future items, so matching nothing today is legitimate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from globalmart.config import GlobalmartError
from globalmart.domains import AiSelection, Domain, DomainManifest

#: Channel name -> (SDK attribute candidates, the `AiSelection` field that selects it).
#: Agent personalities are org-scoped today and AI knowledge is not modelled by the SDK at
#: all; a channel the model does not carry is simply empty rather than an error, so the
#: manifest schema is ready for them without breaking when they arrive.
AI_CHANNELS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("memory_items", ("memory_items",), "memory_item_ids"),
    ("parameters", ("parameters",), "parameter_ids"),
    ("agents", ("agents", "agent_personalities"), "agent_ids"),
    ("knowledge", ("ai_knowledge", "knowledge", "knowledge_items"), "knowledge_ids"),
)


class MissingAiContextError(GlobalmartError):
    """A domain selects an AI object that does not exist in the parent."""


@dataclass(frozen=True)
class AiContextSelection:
    """What one child's AI channels hold."""

    domain_key: str
    objects: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    #: Tags that matched nothing. Reported, never fatal.
    unmatched_tags: tuple[str, ...] = ()

    def ids(self) -> frozenset[str]:
        return frozenset(
            str(obj.id) for objects in self.objects.values() for obj in objects
        )

    def counts(self) -> dict[str, int]:
        return {channel: len(objects) for channel, objects in self.objects.items()}


def _pool(model: Any, attributes: tuple[str, ...]) -> dict[str, Any]:
    analytics = model.analytics
    for attribute in attributes:
        objects = getattr(analytics, attribute, None)
        if objects:
            return {str(obj.id): obj for obj in objects}
    return {}


def _selected_ids(selection: AiSelection, field_name: str) -> tuple[str, ...]:
    return tuple(getattr(selection, field_name))


def filter_ai_context(
    model: Any, domain: Domain, manifest: DomainManifest
) -> AiContextSelection:
    """`domain.ai` ∪ `manifest.shared.ai`, resolved against the parent."""
    selections = (domain.ai, manifest.shared.ai)
    objects: dict[str, tuple[Any, ...]] = {}
    matched_tags: set[str] = set()

    wanted_tags = set(domain.ai.memory_item_tags) | set(manifest.shared.ai.memory_item_tags)

    for channel, attributes, field_name in AI_CHANNELS:
        pool = _pool(model, attributes)
        keep: dict[str, Any] = {}

        for selection in selections:
            for identifier in _selected_ids(selection, field_name):
                obj = pool.get(identifier)
                if obj is None:
                    raise MissingAiContextError(
                        f"domain {domain.key!r}: ai.{field_name} names {identifier!r}, which "
                        "does not exist in the parent workspace"
                    )
                keep[identifier] = obj

        if channel == "memory_items" and wanted_tags:
            for identifier, obj in pool.items():
                tags = {str(tag) for tag in (getattr(obj, "tags", None) or [])}
                hit = tags & wanted_tags
                if hit:
                    keep[identifier] = obj
                    matched_tags |= hit

        objects[channel] = tuple(keep[key] for key in sorted(keep))

    return AiContextSelection(
        domain_key=domain.key,
        objects=objects,
        unmatched_tags=tuple(sorted(wanted_tags - matched_tags)),
    )
