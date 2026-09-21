"""Builds each workspace's routing description by asking the workspace.

The orchestrator routes on descriptions, and where those come from is not a convenience
question. "Can an orchestrator discover what a workspace covers, or must someone write it by
hand?" is the first item on AIS-55's gap list, and Infobip's portal — which adds A2A
connections — hits it on day one. Hand-writing four descriptions would answer it by
assumption. So the profiler generates them, and what it has to reach for *is* the finding.

**What A2A gives you: nothing useful.** Measured against all four demo workspaces on
2026-09-21, every agent card is identical:

    name         GoodData AI Agent
    description  GoodData Analytics AI Agent
    skills       visualization, what_if_analysis, key_driver_analysis, … (9)

Those skills are protocol capabilities, not subject matter. Two workspaces holding completely
different data models advertise the same card. An orchestrator given only A2A cannot tell
them apart, let alone route between them — which is the gap, stated as a measurement rather
than an opinion.

**So the profiler reads metadata instead**: the workspace's own title and description, the
datasets it models, the metrics it exposes, and any AI memory items authored for it. That is
four extra API calls per workspace, none of them part of A2A, all of them requiring
credentials beyond what an agent connection needs.

**Deterministic, not summarised by a model.** Same workspace, same description, every run —
so a registry diff means the workspace changed rather than the weather. It reads longer than
a human would write, and that is the right trade: a routing prompt is read by a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from gd_agents.registry import Registry, WorkspaceEntry
from gd_agents.transport import Host, TransportError, entities

#: How many of each kind to name in a description. Enough to convey subject matter, few
#: enough that four of these stay a prompt rather than a catalog.
SAMPLE = 12


@dataclass
class Probe:
    """What one workspace says about itself."""

    workspace: str
    title: str = ""
    description: str = ""
    datasets: tuple[str, ...] = ()
    subjects: tuple[str, ...] = ()
    """Titles of the workspace's *fact* datasets — what it actually measures.

    The distinguishing signal. Dimension datasets are conformed and therefore nearly
    identical across workspaces, so a description built from them says "Currency, Country,
    Customer" for every workspace and routes nothing."""
    metrics: tuple[str, ...] = ()
    metric_count: int = 0
    knowledge: tuple[str, ...] = ()
    agent_card_description: str = ""
    agent_skills: tuple[str, ...] = ()
    reached: list[str] = field(default_factory=list)
    """Which API paths had to be called. This is the gap-list evidence."""


def _titles(rows: list[dict[str, Any]], key: str = "title") -> tuple[str, ...]:
    """Titles in declared order, de-duplicated.

    Knowledge is chunked per section, so several memory items share one document title.
    Listing it four times tells a router nothing and costs it tokens.
    """
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        value = (row.get("attributes") or {}).get(key) or row.get("id")
        if not value:
            continue
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


#: Markers of a *derived* metric — a period comparison or a change against another metric.
#: They are real metrics and stay available, but they say nothing about subject matter that
#: the metric they derive from has not already said, so they sort last.
DERIVED_MARKERS = ("MoM:", "YoY:", "QoQ:", " vs ", "Change")


def _base_first(metrics: tuple[str, ...]) -> tuple[str, ...]:
    base = [m for m in metrics if not any(marker in m for marker in DERIVED_MARKERS)]
    derived = [m for m in metrics if any(marker in m for marker in DERIVED_MARKERS)]
    return tuple(base + derived)


def probe_workspace(host: Host, workspace: str) -> Probe:
    """Read everything a description can be built from. Read-only."""
    result = Probe(workspace=workspace)

    try:
        card = host.get(f"/api/v1/ai/workspaces/{workspace}/a2a")
        result.reached.append(f"/api/v1/ai/workspaces/{workspace}/a2a")
        result.agent_card_description = str((card or {}).get("description") or "")
        result.agent_skills = tuple(s.get("id", "") for s in (card or {}).get("skills") or [])
    except TransportError:
        # A workspace with no A2A agent can still be described; it just cannot be asked.
        pass

    payload = host.get(f"/api/v1/entities/workspaces/{workspace}")
    result.reached.append(f"/api/v1/entities/workspaces/{workspace}")
    attributes = ((payload or {}).get("data") or {}).get("attributes") or {}
    result.title = str(attributes.get("name") or workspace)
    result.description = str(attributes.get("description") or "")

    for kind, sink in (("datasets", "datasets"), ("metrics", "metrics"), ("memoryItems", "knowledge")):
        try:
            rows = entities(host, workspace, kind)
            result.reached.append(f"/api/v1/entities/workspaces/{workspace}/{kind}")
        except TransportError:
            rows = []
        if sink == "metrics":
            result.metric_count = len(rows)
        if sink == "datasets":
            # Fact datasets are identified by id, not by title: the id is `fact_order_line`
            # while the title is "Order Line". Filtering on the title finds nothing.
            result.subjects = _titles([r for r in rows if str(r.get("id", "")).startswith("fact")])
        setattr(result, sink, _titles(rows))

    return result


def describe(probe: Probe, *, sample: int = SAMPLE) -> str:
    """Condense a probe into the one paragraph the routing prompt carries.

    Subject matter first, because that is what a routing decision turns on. Vocabulary
    second, because questions arrive in the user's words and the router has to bridge them.
    Deliberately omits anything an orchestrator cannot act on — ids, counts of objects
    nobody asked about, the agent card's generic blurb.
    """
    parts: list[str] = []

    if probe.description:
        parts.append(probe.description.rstrip("."))

    if probe.subjects:
        parts.append("Measures " + ", ".join(probe.subjects[:sample]))

    if probe.metrics:
        ordered = _base_first(probe.metrics)
        shown = ", ".join(ordered[:sample])
        remaining = probe.metric_count - min(sample, len(ordered))
        more = f" and {remaining} more" if remaining > 0 else ""
        parts.append(f"Metrics include {shown}{more}")

    if probe.knowledge:
        parts.append(f"Has authored knowledge on {', '.join(probe.knowledge[:4])}")

    return ". ".join(part.strip().rstrip(".") for part in parts if part.strip()) + "."


def build_registry(
    host: Host, workspaces: list[str], *, token_env: str, sample: int = SAMPLE
) -> tuple[Registry, list[Probe]]:
    """Profile every workspace and assemble the registry the orchestrator loads."""
    today = date.today().isoformat()
    probes = [probe_workspace(host, workspace) for workspace in workspaces]
    entries = tuple(
        WorkspaceEntry(
            id=probe.workspace,
            title=probe.title,
            description=describe(probe, sample=sample),
            profiled_at=today,
        )
        for probe in probes
    )
    return Registry(host=host.url, token_env=token_env, entries=entries), probes


def discovery_findings(probes: list[Probe]) -> list[str]:
    """What the profiler had to do, phrased for the gap list.

    Written here rather than in a document because it is derived from what actually happened
    on a real run, and a finding reconstructed from memory afterwards is a guess.
    """
    findings: list[str] = []
    if not probes:
        return findings

    cards = {probe.agent_card_description for probe in probes if probe.agent_card_description}
    if len(cards) == 1 and len(probes) > 1:
        only = next(iter(cards))
        findings.append(
            f"All {len(probes)} workspaces advertise an identical A2A agent card "
            f"({only!r}), so the card cannot be used to tell them apart or to route between "
            "them. Subject matter is not discoverable over A2A."
        )

    skills = {probe.agent_skills for probe in probes if probe.agent_skills}
    if len(skills) == 1 and len(probes) > 1:
        findings.append(
            "Advertised skills are protocol capabilities (visualization, key-driver analysis "
            "and so on), identical across workspaces holding different data models. They "
            "describe what the agent can do, never what it knows about."
        )

    kinds = {"datasets", "metrics", "memoryItems", "attributes", "visualizationObjects"}
    extra = sorted(
        {
            path.rsplit("/", 1)[-1]
            for probe in probes
            for path in probe.reached
            if path.rsplit("/", 1)[-1] in kinds
        }
    )
    if extra:
        findings.append(
            "Building a routing description required reading "
            f"{', '.join(extra)} through the metadata API — calls outside A2A, needing "
            "credentials beyond what an agent connection carries. An orchestrator that only "
            "holds an A2A endpoint cannot produce these descriptions."
        )

    undescribed = [probe.workspace for probe in probes if not probe.description]
    if undescribed:
        findings.append(
            f"{len(undescribed)} workspace(s) carry no description of their own "
            f"({', '.join(undescribed)}), so the subject matter had to be inferred from "
            "dataset and metric names."
        )

    return findings
