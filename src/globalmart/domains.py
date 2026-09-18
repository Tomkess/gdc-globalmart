"""The domain membership manifest — schema, strict loader, canonical dumper.

``config/domains.yaml`` is the one place in the repo that says which dashboards,
visualizations and AI-context objects belong to each domain. Nothing infers membership from
an object id ever again.

**Why strict parsing matters here more than usual.** The predecessor decided membership by
testing ``viz_id.startswith(f"viz_{domain}_")`` and included a dashboard only when *every*
tile matched, so a dashboard whose tiles spanned two domains matched nothing and was dropped
with no error. Replacing an inference with a declaration only helps if the declaration is
read exactly as written: a manifest that says ``dashboard:`` instead of ``dashboards:`` must
fail loudly, not quietly mean "this domain has no dashboards" — which is the same silent
drop wearing a different hat. Hence: unknown keys raise, naming the key and its dotted path.

Every list field loads as a ``tuple`` so a loaded manifest cannot be mutated by a consumer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from globalmart.config import GlobalmartError

#: Schema version this loader understands. A manifest carrying anything else raises rather
#: than being parsed leniently — a future v2 will mean something, and guessing what is worse
#: than refusing.
SCHEMA_VERSION = 1

DEFAULT_WORKSPACE_ID_TEMPLATE = "globalmart-{key_kebab}"
DEFAULT_WORKSPACE_NAME_TEMPLATE = "GlobalMart — {label}"

_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

#: Reasons that say nothing. Fatal under ``--strict``, which is the CI gate — so a
#: bootstrap-generated manifest full of ``TODO:`` placeholders cannot go green unreviewed.
PLACEHOLDER_REASONS = frozenset({"todo", "tbd", "n/a", "na", "none", "-", "?"})

_MANIFEST_KEYS = frozenset(
    {
        "version",
        "parent_workspace_id",
        "workspace_id_template",
        "workspace_name_template",
        "domains",
        "shared",
        "unassigned",
    }
)
_DOMAIN_KEYS = frozenset(
    {
        "key",
        "label",
        "description",
        "workspace_id",
        "workspace_name",
        "dashboards",
        "visualizations",
        "ai",
        "ldm_include",
    }
)
_AI_KEYS = frozenset(
    {"memory_item_ids", "memory_item_tags", "parameter_ids", "agent_ids", "knowledge_ids"}
)
_SHARED_KEYS = frozenset({"dashboards", "visualizations", "ai"})
_UNASSIGNED_KEYS = frozenset({"dashboards", "visualizations", "ai"})
_EXCLUSION_KEYS = frozenset({"id", "reason"})


class DomainManifestError(GlobalmartError):
    """The manifest is unparseable, schema-invalid, or internally inconsistent."""


@dataclass(frozen=True)
class AiSelection:
    """Which AI-context objects a domain (or every domain, under ``shared``) receives.

    ``memory_item_tags`` is the one rule rather than an id list in the whole manifest: a
    memory item carrying any listed tag is included. AI memory is expected to grow, and
    requiring an id edit per new item would guarantee the manifest falls behind.
    """

    memory_item_ids: tuple[str, ...] = ()
    memory_item_tags: tuple[str, ...] = ()
    parameter_ids: tuple[str, ...] = ()
    agent_ids: tuple[str, ...] = ()
    knowledge_ids: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return not (
            self.memory_item_ids
            or self.memory_item_tags
            or self.parameter_ids
            or self.agent_ids
            or self.knowledge_ids
        )

    def all_ids(self) -> tuple[str, ...]:
        """Every explicitly named id — tags excluded, since a tag is not an id."""
        return (
            *self.memory_item_ids,
            *self.parameter_ids,
            *self.agent_ids,
            *self.knowledge_ids,
        )


@dataclass(frozen=True)
class Exclusion:
    """One object deliberately in no domain, with the reason it is excluded."""

    id: str
    reason: str

    def reason_is_placeholder(self) -> bool:
        stripped = self.reason.strip()
        if not stripped:
            return True
        if stripped.lower() in PLACEHOLDER_REASONS:
            return True
        return stripped.upper().startswith("TODO:")


@dataclass(frozen=True)
class Domain:
    """One domain: a child workspace's identity and its explicit object membership."""

    key: str
    label: str
    description: str
    workspace_id: str
    workspace_name: str | None = None
    dashboards: tuple[str, ...] = ()
    visualizations: tuple[str, ...] = ()
    ai: AiSelection = field(default_factory=AiSelection)
    #: Dataset ids seeded into this child's LDM *beyond* what FEAT-004's closure reaches, so
    #: there is room to author new metrics and visualizations on tables today's dashboards
    #: do not touch. An LDM concern only: never coverage of a dashboard, visualization or AI
    #: object, and not the ``shared:`` block.
    ldm_include: tuple[str, ...] = ()


@dataclass(frozen=True)
class SharedSelection:
    """Objects that belong in *every* child. Counts as coverage."""

    dashboards: tuple[str, ...] = ()
    visualizations: tuple[str, ...] = ()
    ai: AiSelection = field(default_factory=AiSelection)


@dataclass(frozen=True)
class UnassignedSelection:
    """Deliberate, reasoned exclusions. Counts as coverage — but only with a real reason."""

    dashboards: tuple[Exclusion, ...] = ()
    visualizations: tuple[Exclusion, ...] = ()
    ai: tuple[Exclusion, ...] = ()

    def all_exclusions(self) -> tuple[Exclusion, ...]:
        return (*self.dashboards, *self.visualizations, *self.ai)


@dataclass(frozen=True)
class DomainManifest:
    """The whole manifest. Consumers reach it only through the accessors below."""

    version: int
    parent_workspace_id: str
    workspace_id_template: str
    workspace_name_template: str
    domains: tuple[Domain, ...]
    shared: SharedSelection = field(default_factory=SharedSelection)
    unassigned: UnassignedSelection = field(default_factory=UnassignedSelection)
    path: Path | None = None

    def by_key(self, key: str) -> Domain:
        for domain in self.domains:
            if domain.key == key:
                return domain
        raise DomainManifestError(
            f"No domain {key!r} in the manifest. Known keys: {', '.join(self.keys())}"
        )

    def keys(self) -> tuple[str, ...]:
        """Domain keys in canonical (sorted) order, so consumers iterate deterministically."""
        return tuple(sorted(domain.key for domain in self.domains))

    def resolve_workspace_name(self, domain: Domain) -> str:
        """The published display name.

        The only sanctioned producer of the string FEAT-004 passes to
        ``publish_workspace(..., workspace_name=...)``. No caller concatenates
        ``"GlobalMart — " + label`` itself, which is how the label and the published name
        would drift apart.
        """
        if domain.workspace_name:
            return domain.workspace_name
        return self.workspace_name_template.format(label=domain.label, key=domain.key)

    def resolve_workspace_id(self, domain: Domain) -> str:
        return self.workspace_id_template.format(key_kebab=key_kebab(domain.key), key=domain.key)

    def unassigned_ids(self) -> frozenset[str]:
        """Every excluded id, flattened — for callers that need membership, not reasons."""
        return frozenset(exclusion.id for exclusion in self.unassigned.all_exclusions())


def key_kebab(key: str) -> str:
    """``two_words`` -> ``two-words``. The one place the snake/kebab split is spelled out.

    Domain keys are snake_case and child workspace ids are kebab-case; this is the whole of
    that translation, so no caller re-implements it slightly differently.
    """
    return key.replace("_", "-")


# --- loading -----------------------------------------------------------------


def _require_mapping(node: Any, path: str) -> dict[str, Any]:
    if not isinstance(node, dict):
        raise DomainManifestError(f"{path}: expected a mapping, got {type(node).__name__}")
    return node


def _reject_unknown_keys(node: dict[str, Any], allowed: frozenset[str], path: str) -> None:
    unknown = sorted(set(node) - allowed)
    if unknown:
        raise DomainManifestError(
            f"{path}: unknown key(s) {', '.join(repr(k) for k in unknown)}. "
            f"Allowed here: {', '.join(sorted(allowed))}. "
            "A typo must not silently mean 'empty'."
        )


def _str_tuple(node: Any, path: str, *, sort: bool = True) -> tuple[str, ...]:
    if node is None:
        return ()
    if not isinstance(node, list):
        raise DomainManifestError(f"{path}: expected a list of strings, got {type(node).__name__}")
    values: list[str] = []
    for index, item in enumerate(node):
        if not isinstance(item, str):
            raise DomainManifestError(
                f"{path}[{index}]: expected a string, got {type(item).__name__}"
            )
        values.append(item)
    duplicates = sorted({v for v in values if values.count(v) > 1})
    if duplicates:
        raise DomainManifestError(f"{path}: duplicate entries {', '.join(duplicates)}")
    return tuple(sorted(values)) if sort else tuple(values)


def _required_str(node: dict[str, Any], key: str, path: str) -> str:
    value = node.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DomainManifestError(f"{path}.{key}: required, must be a non-empty string")
    return value


def _parse_ai(node: Any, path: str) -> AiSelection:
    if node is None:
        return AiSelection()
    mapping = _require_mapping(node, path)
    _reject_unknown_keys(mapping, _AI_KEYS, path)
    return AiSelection(
        memory_item_ids=_str_tuple(mapping.get("memory_item_ids"), f"{path}.memory_item_ids"),
        memory_item_tags=_str_tuple(mapping.get("memory_item_tags"), f"{path}.memory_item_tags"),
        parameter_ids=_str_tuple(mapping.get("parameter_ids"), f"{path}.parameter_ids"),
        agent_ids=_str_tuple(mapping.get("agent_ids"), f"{path}.agent_ids"),
        knowledge_ids=_str_tuple(mapping.get("knowledge_ids"), f"{path}.knowledge_ids"),
    )


def _parse_exclusions(node: Any, path: str) -> tuple[Exclusion, ...]:
    if node is None:
        return ()
    if not isinstance(node, list):
        raise DomainManifestError(f"{path}: expected a list of {{id, reason}} mappings")
    exclusions: list[Exclusion] = []
    for index, item in enumerate(node):
        item_path = f"{path}[{index}]"
        mapping = _require_mapping(item, item_path)
        _reject_unknown_keys(mapping, _EXCLUSION_KEYS, item_path)
        identifier = _required_str(mapping, "id", item_path)
        reason = mapping.get("reason")
        if not isinstance(reason, str):
            raise DomainManifestError(
                f"{item_path}.reason: required — an exclusion must be justified in words"
            )
        exclusions.append(Exclusion(id=identifier, reason=reason))
    ids = [exclusion.id for exclusion in exclusions]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise DomainManifestError(f"{path}: duplicate excluded id(s) {', '.join(duplicates)}")
    return tuple(sorted(exclusions, key=lambda exclusion: exclusion.id))


def _parse_domain(node: Any, path: str) -> Domain:
    mapping = _require_mapping(node, path)
    _reject_unknown_keys(mapping, _DOMAIN_KEYS, path)

    key = _required_str(mapping, "key", path)
    if not _KEY_PATTERN.match(key):
        raise DomainManifestError(
            f"{path}.key: {key!r} must be snake_case matching {_KEY_PATTERN.pattern}"
        )

    workspace_name = mapping.get("workspace_name")
    if workspace_name is not None and (
        not isinstance(workspace_name, str) or not workspace_name.strip()
    ):
        raise DomainManifestError(f"{path}.workspace_name: must be a non-empty string when present")

    return Domain(
        key=key,
        label=_required_str(mapping, "label", path),
        description=_required_str(mapping, "description", path),
        workspace_id=_required_str(mapping, "workspace_id", path),
        workspace_name=workspace_name,
        dashboards=_str_tuple(mapping.get("dashboards"), f"{path}.dashboards"),
        visualizations=_str_tuple(mapping.get("visualizations"), f"{path}.visualizations"),
        ai=_parse_ai(mapping.get("ai"), f"{path}.ai"),
        # Existence against the parent's ``ldm.datasets`` is check_coverage's job — this
        # loader never reads a layout tree.
        ldm_include=_str_tuple(mapping.get("ldm_include"), f"{path}.ldm_include"),
    )


def _validate(manifest: DomainManifest) -> None:
    """Everything checkable without the parent tree."""
    if not manifest.domains:
        raise DomainManifestError("domains: at least one domain is required")

    for attribute in ("key", "label", "workspace_id"):
        seen: dict[str, int] = {}
        for index, domain in enumerate(manifest.domains):
            value = getattr(domain, attribute)
            if value in seen:
                raise DomainManifestError(
                    f"domains[{index}].{attribute}: {value!r} duplicates domains[{seen[value]}]"
                )
            seen[value] = index

    for index, domain in enumerate(manifest.domains):
        path = f"domains[{index}]"
        if domain.workspace_id == manifest.parent_workspace_id:
            raise DomainManifestError(
                f"{path}.workspace_id: {domain.workspace_id!r} is the parent workspace — "
                "a child would overwrite the source it was derived from"
            )
        expected = manifest.resolve_workspace_id(domain)
        if domain.workspace_id != expected:
            raise DomainManifestError(
                f"{path}.workspace_id: {domain.workspace_id!r} does not match "
                f"workspace_id_template, which renders {expected!r} for key {domain.key!r}"
            )
        # ldm_include deliberately does not count: it widens the child's LDM, it does not
        # declare membership of anything.
        if not domain.dashboards and not domain.visualizations:
            raise DomainManifestError(
                f"{path}: domain {domain.key!r} lists no dashboards and no visualizations. "
                "ldm_include does not count — it is LDM headroom, not membership."
            )


def load_domains(path: Path) -> DomainManifest:
    """Parse and validate a manifest. Never reads a layout tree or contacts a host."""
    path = Path(path)
    if not path.exists():
        raise DomainManifestError(f"No domain manifest at {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    document = _require_mapping(raw, str(path))
    _reject_unknown_keys(document, _MANIFEST_KEYS, str(path))

    version = document.get("version")
    if version != SCHEMA_VERSION:
        raise DomainManifestError(
            f"{path}: version {version!r} is not supported (this loader understands "
            f"version {SCHEMA_VERSION})"
        )

    domains_node = document.get("domains")
    if not isinstance(domains_node, list):
        raise DomainManifestError(f"{path}: 'domains' must be a list")

    domains = tuple(
        sorted(
            (_parse_domain(node, f"domains[{index}]") for index, node in enumerate(domains_node)),
            key=lambda domain: domain.key,
        )
    )

    shared_node = document.get("shared")
    if shared_node is None:
        shared = SharedSelection()
    else:
        shared_map = _require_mapping(shared_node, "shared")
        _reject_unknown_keys(shared_map, _SHARED_KEYS, "shared")
        shared = SharedSelection(
            dashboards=_str_tuple(shared_map.get("dashboards"), "shared.dashboards"),
            visualizations=_str_tuple(shared_map.get("visualizations"), "shared.visualizations"),
            ai=_parse_ai(shared_map.get("ai"), "shared.ai"),
        )

    unassigned_node = document.get("unassigned")
    if unassigned_node is None:
        unassigned = UnassignedSelection()
    else:
        unassigned_map = _require_mapping(unassigned_node, "unassigned")
        _reject_unknown_keys(unassigned_map, _UNASSIGNED_KEYS, "unassigned")
        unassigned = UnassignedSelection(
            dashboards=_parse_exclusions(unassigned_map.get("dashboards"), "unassigned.dashboards"),
            visualizations=_parse_exclusions(
                unassigned_map.get("visualizations"), "unassigned.visualizations"
            ),
            ai=_parse_exclusions(unassigned_map.get("ai"), "unassigned.ai"),
        )

    manifest = DomainManifest(
        version=version,
        parent_workspace_id=_required_str(document, "parent_workspace_id", str(path)),
        workspace_id_template=document.get(
            "workspace_id_template", DEFAULT_WORKSPACE_ID_TEMPLATE
        ),
        workspace_name_template=document.get(
            "workspace_name_template", DEFAULT_WORKSPACE_NAME_TEMPLATE
        ),
        domains=domains,
        shared=shared,
        unassigned=unassigned,
        path=path,
    )
    _validate(manifest)
    return manifest


# --- dumping -----------------------------------------------------------------


def _ai_to_dict(ai: AiSelection) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name in ("memory_item_ids", "memory_item_tags", "parameter_ids", "agent_ids", "knowledge_ids"):
        values = getattr(ai, name)
        if values:
            out[name] = sorted(values)
    return out


def manifest_to_dict(manifest: DomainManifest) -> dict[str, Any]:
    """The canonical mapping a manifest serialises to.

    Fixed key order top-down, domains sorted by key, every id list sorted lexically — so
    adding one dashboard to one domain is a one-line diff rather than a reshuffle.
    """
    domains: list[dict[str, Any]] = []
    for domain in sorted(manifest.domains, key=lambda d: d.key):
        entry: dict[str, Any] = {
            "key": domain.key,
            "label": domain.label,
            "description": domain.description,
            "workspace_id": domain.workspace_id,
        }
        if domain.workspace_name:
            entry["workspace_name"] = domain.workspace_name
        entry["dashboards"] = sorted(domain.dashboards)
        entry["visualizations"] = sorted(domain.visualizations)
        ai = _ai_to_dict(domain.ai)
        if ai:
            entry["ai"] = ai
        if domain.ldm_include:
            entry["ldm_include"] = sorted(domain.ldm_include)
        domains.append(entry)

    document: dict[str, Any] = {
        "version": manifest.version,
        "parent_workspace_id": manifest.parent_workspace_id,
        "workspace_id_template": manifest.workspace_id_template,
        "workspace_name_template": manifest.workspace_name_template,
        "domains": domains,
    }

    shared: dict[str, Any] = {
        "dashboards": sorted(manifest.shared.dashboards),
        "visualizations": sorted(manifest.shared.visualizations),
    }
    shared_ai = _ai_to_dict(manifest.shared.ai)
    if shared_ai:
        shared["ai"] = shared_ai
    document["shared"] = shared

    document["unassigned"] = {
        name: [
            {"id": exclusion.id, "reason": exclusion.reason}
            for exclusion in sorted(getattr(manifest.unassigned, name), key=lambda e: e.id)
        ]
        for name in ("dashboards", "visualizations", "ai")
    }

    return document


def dump_domains(manifest: DomainManifest, path: Path) -> Path:
    """Write canonical YAML. Deterministic: two dumps of one manifest are byte-identical."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        manifest_to_dict(manifest),
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=100,
        indent=2,
    )
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")
    return path


def with_path(manifest: DomainManifest, path: Path) -> DomainManifest:
    """Same manifest, different provenance — used after a dump so ``path`` is not stale."""
    return replace(manifest, path=Path(path))
