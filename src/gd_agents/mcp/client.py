"""One workspace's MCP endpoint, and what it actually offers.

`POST /api/v1/actions/workspaces/{ws}/ai/mcp`, JSON-RPC 2.0 over MCP's streamable-http
transport. No handshake: `tools/list` and `tools/call` work against a bare endpoint.

**What the endpoint exposes is not what FEAT-014's spec assumed, and the difference matters
to the comparison.** The spec was written expecting seventeen tools with four selected. A
live `tools/list` on 2026-09-23 returned **three**:

    create_visualization   natural language in, a rendered chart out
    search_tools           semantic search over the tools that are *not* listed
    call_tool              a dispatcher: invoke any of them by name

So the real surface is a **gateway**. The tools the spec names — `list_workspace_metrics`,
`list_workspace_attributes`, `execute_query`, `get_workspace_info` — exist and work, reached
through `call_tool` by name with no search first. Three consequences:

**The four-tool restriction is a client-side choice, not a server-side one.** A caller
decides which names it is willing to dispatch. That is what `MCPClient.tools` is: a
whitelist enforced in `call`, so "restricted to a small tool set" is a property of this code
and can be stated as one rather than assumed of the server.

**Tool-choice degradation is not the failure mode.** Four workspaces exposing three
meta-tools each is twelve, well under the ~30 where selection is understood to degrade. The
spec's flat-versus-nested contrast has to be argued on context and round trips instead.

**`create_visualization` is close to what A2A offers.** A natural-language tool on the MCP
endpoint weakens the neat story that "A2A delegates reasoning, MCP delegates execution" —
GoodData's MCP will also take a sentence. Any honest recommendation has to say so.
"""

from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from gd_agents.transport import Host, TransportError

#: The MCP surface this orchestrator is willing to dispatch, and why each one is here.
#:
#: FEAT-014 AC 3 fixes the set at four and says a fifth is a deliberate decision recorded
#: with a reason. `ai_search` is that fifth, and the reason is measured: on
#: `globalmart-customer`, an unfiltered `list_workspace_metrics` returns 173 KB — **~43,000
#: tokens** for 186 metrics — where `ai_search` answers the same need in 200–1,800 tokens
#: depending on the question, in about 1.4 seconds. Leaving it out would not have made the
#: comparison stricter, it would have made the MCP arm a strawman that no competent
#: integrator would build.
DEFAULT_TOOLS: tuple[str, ...] = (
    "get_workspace_info",
    "ai_search",
    "list_workspace_metrics",
    "list_workspace_attributes",
    "execute_query",
)

#: The three the endpoint itself advertises. `call_tool` is the dispatcher everything else
#: goes through; the others are listed so a probe can report the surface honestly.
GATEWAY_TOOLS: tuple[str, ...] = ("create_visualization", "search_tools", "call_tool")


class MCPError(Exception):
    """The endpoint refused, or answered with something that is not a result."""


@dataclass
class ToolCall:
    """One dispatched tool, with what it cost.

    Round trips and payload size are the comparison's substance, so they are recorded per
    call rather than totalled at the end: "which call put 43,000 tokens into context" is the
    question worth answering, and a total cannot.
    """

    tool: str
    arguments: dict[str, Any]
    chars: int = 0
    latency_ms: int = 0
    error: str | None = None

    def ok(self) -> bool:
        return self.error is None

    def approx_tokens(self) -> int:
        """Characters over four. Crude, and honest about being crude — the point is the
        order of magnitude between a few hundred and 43,000, which no tokeniser will
        change."""
        return self.chars // 4


@dataclass
class MCPClient:
    """One workspace's MCP endpoint, restricted to a named set of tools."""

    host: Host
    workspace: str
    tools: tuple[str, ...] = DEFAULT_TOOLS
    timeout: float = 120.0
    calls: list[ToolCall] = field(default_factory=list)

    def endpoint(self) -> str:
        return f"/api/v1/actions/workspaces/{urllib.parse.quote(self.workspace, safe='')}/ai/mcp"

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": len(self.calls) + 1, "method": method}
        if params is not None:
            body["params"] = params
        payload = self.host.post(
            self.endpoint(),
            body,
            timeout=self.timeout,
            accept="application/json, text/event-stream",
        )
        if not isinstance(payload, dict):
            raise MCPError(f"{method} answered with {type(payload).__name__}, not an object")
        if "error" in payload:
            raise MCPError(f"{method} -> {payload['error']}")
        return payload.get("result")

    def list_tools(self) -> tuple[str, ...]:
        """What the endpoint advertises — the gateway, not the catalogue behind it."""
        result = self._rpc("tools/list") or {}
        return tuple(str(t.get("name")) for t in result.get("tools") or [] if t.get("name"))

    def call(self, tool: str, **arguments: Any) -> str:
        """Dispatch one tool through the gateway and return its text content.

        Refuses a tool outside `self.tools`. The restriction is the experiment: the whole
        comparison rests on the MCP arm having a small, stated tool set, and a set that can
        quietly grow measures nothing.
        """
        if tool not in self.tools:
            raise MCPError(
                f"{tool!r} is not in this lane's tool set ({', '.join(self.tools)}). "
                "Widening it is a change to the comparison, not a call site detail."
            )

        record = ToolCall(tool=tool, arguments=dict(arguments))
        started = time.monotonic()
        try:
            result = self._rpc(
                "tools/call",
                {"name": "call_tool", "arguments": {"name": tool, "arguments": arguments}},
            )
        except (MCPError, TransportError) as error:
            record.error = str(error)[:300]
            record.latency_ms = int((time.monotonic() - started) * 1000)
            self.calls.append(record)
            raise MCPError(record.error) from error

        text = text_of(result)
        record.chars = len(text)
        record.latency_ms = int((time.monotonic() - started) * 1000)
        self.calls.append(record)
        return text

    def round_trips(self) -> int:
        return len(self.calls)

    def chars_in(self) -> int:
        """Every character every tool put into the caller's context.

        Under A2A this number does not exist: the catalogue never leaves the workspace. It is
        the single clearest difference between the two protocols and it lands on whoever pays
        for the model.
        """
        return sum(call.chars for call in self.calls)


def text_of(result: Any) -> str:
    """The text content of an MCP tool result.

    A result is `{"content": [{"type": "text", "text": ...}]}`. Non-text parts are skipped
    rather than stringified: a blob rendered as its repr would land in a token count as if it
    were something the model read.
    """
    if not isinstance(result, dict):
        return ""
    parts = result.get("content")
    if not isinstance(parts, list):
        return ""
    return "".join(
        part["text"] for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)
    )
