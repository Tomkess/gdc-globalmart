"""What the MCP endpoint costs, measured rather than assumed.

FEAT-009's profiler exists because "can an orchestrator discover what a workspace covers?"
had to be answered by asking rather than by reading the documentation. This is the same move
for the other protocol: before writing a lane that uses these tools, find out what they
return and what it costs to put in a model's context.

The headline it produces is the comparison's most quotable number: an unfiltered
`list_workspace_metrics` on `globalmart-customer` returns **~43,000 tokens** for 186
metrics, against a few hundred for `ai_search` answering the same need. The gap is not a
detail of one workspace — it scales with how well modelled a workspace is, so it is *worst*
for the customers who have invested most in their semantic layer.

A first hand measurement of this put it at ~90,000 tokens, by counting the JSON-escaped
envelope rather than the text a model would actually read. Roughly double, and wrong. Hence
this module: the number goes into a report only after something that knows how to read the
response has produced it twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gd_agents.mcp.client import GATEWAY_TOOLS, MCPClient, MCPError

#: What `ai_search` is asked, per workspace, to compare against listing everything. A real
#: question rather than a keyword: the point is whether one call can replace the catalogue.
PROBE_QUESTION = "metrics and attributes for a monthly trend"


@dataclass
class ToolCost:
    tool: str
    chars: int = 0
    latency_ms: int = 0
    error: str | None = None

    def approx_tokens(self) -> int:
        return self.chars // 4


@dataclass
class WorkspaceProbe:
    workspace: str
    advertised: tuple[str, ...] = ()
    costs: list[ToolCost] = field(default_factory=list)

    def cost(self, tool: str) -> ToolCost | None:
        return next((c for c in self.costs if c.tool == tool), None)

    def summary_lines(self) -> list[str]:
        lines = [f"{self.workspace}", f"  advertised    : {', '.join(self.advertised) or 'none'}"]
        for entry in self.costs:
            if entry.error:
                lines.append(f"  {entry.tool:26} FAILED {entry.error[:70]}")
            else:
                lines.append(
                    f"  {entry.tool:26} {entry.approx_tokens():>7,} tok  {entry.latency_ms:>6} ms"
                )
        return lines


def probe_workspace(client: MCPClient) -> WorkspaceProbe:
    """Cost each discovery route on one workspace. Nothing is written anywhere."""
    probe = WorkspaceProbe(workspace=client.workspace)
    try:
        probe.advertised = client.list_tools()
    except (MCPError, Exception) as error:  # noqa: BLE001 - a dead endpoint is a finding
        probe.costs.append(ToolCost(tool="tools/list", error=str(error)[:200]))
        return probe

    for tool, arguments in (
        ("get_workspace_info", {}),
        ("ai_search", {"question": PROBE_QUESTION}),
        ("list_workspace_metrics", {}),
        ("list_workspace_attributes", {}),
    ):
        try:
            client.call(tool, **arguments)
        except MCPError as error:
            probe.costs.append(ToolCost(tool=tool, error=str(error)[:200]))
            continue
        call = client.calls[-1]
        probe.costs.append(ToolCost(tool=tool, chars=call.chars, latency_ms=call.latency_ms))
    return probe


def findings(probes: list[WorkspaceProbe]) -> list[str]:
    """What the run establishes, in sentences that can go to product unedited."""
    found: list[str] = []
    if not probes:
        return found

    advertised = {p.advertised for p in probes if p.advertised}
    if len(advertised) == 1:
        names = ", ".join(next(iter(advertised)))
        found.append(
            f"Every workspace advertises the same {len(next(iter(advertised)))} tools ({names}). "
            "The endpoint is a gateway: the analytical tools are reached through `call_tool` by "
            "name, and `tools/list` does not name them. A caller that trusts `tools/list` to "
            "describe the surface will conclude GoodData's MCP can draw a chart and nothing else."
        )
    if any(set(p.advertised) >= set(GATEWAY_TOOLS) for p in probes):
        found.append(
            "`call_tool` dispatches by name with no `search_tools` call first, so restricting a "
            "lane to a named set of tools is a decision the *client* makes. The server does not "
            "offer a way to narrow what it will run."
        )

    listed = [(p.workspace, c) for p in probes if (c := p.cost("list_workspace_metrics")) and not c.error]
    searched = [(p.workspace, c) for p in probes if (c := p.cost("ai_search")) and not c.error]
    if listed:
        worst = max(listed, key=lambda item: item[1].chars)
        total = sum(c.approx_tokens() for _, c in listed)
        found.append(
            f"An unfiltered `list_workspace_metrics` costs up to ~{worst[1].approx_tokens():,} tokens "
            f"({worst[0]}), and ~{total:,} tokens across all {len(listed)} workspaces. A four-lane "
            "question that lists metrics before querying pays that before any reasoning begins — "
            "and it scales with how well modelled the workspace is, so it is worst for the "
            "customers who have invested most in their semantic layer."
        )
    if listed and searched:
        list_total = sum(c.approx_tokens() for _, c in listed)
        search_total = sum(c.approx_tokens() for _, c in searched)
        if search_total:
            ratio = list_total / search_total
            found.append(
                f"`ai_search` answers the same discovery need for ~{search_total:,} tokens against "
                f"~{list_total:,} — about {ratio:.0f}x cheaper. So MCP's context cost is mostly a "
                "property of how well the client is written, not of the protocol. A caller who "
                "reaches for the obvious tool pays the large number; one who knows about "
                "`ai_search` does not. That is a documentation and defaults problem, and it is "
                "the single most actionable finding here."
            )
    return found


def report(probes: list[WorkspaceProbe]) -> str:
    """The findings as Markdown, for `docs/mcp-findings.md`."""
    lines = [
        "# What GoodData's MCP endpoint offers, measured",
        "",
        f"Generated by `gd-agents mcp-probe` against {len(probes)} workspace(s). "
        "Not written from memory — every number below came from a live call.",
        "",
        "## Findings",
        "",
    ]
    lines += [f"- {finding}" for finding in findings(probes)] or ["- nothing established"]
    lines += [
        "",
        "## Cost per discovery route",
        "",
        "| workspace | tool | approx tokens | ms |",
        "|---|---|---:|---:|",
    ]
    for probe in probes:
        for entry in probe.costs:
            value = "FAILED" if entry.error else f"{entry.approx_tokens():,}"
            latency = "" if entry.error else str(entry.latency_ms)
            lines.append(f"| {probe.workspace} | `{entry.tool}` | {value} | {latency} |")
    lines.append("")
    return "\n".join(lines)


def probe_all(host: Any, workspaces: list[str], *, timeout: float = 120.0) -> list[WorkspaceProbe]:
    return [probe_workspace(MCPClient(host=host, workspace=w, timeout=timeout)) for w in workspaces]
