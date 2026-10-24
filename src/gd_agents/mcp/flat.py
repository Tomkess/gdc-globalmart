"""FEAT-014's flat arm: every workspace's MCP tools in one host context, routed by tool choice.

The naive integration, and the one a customer tries first: connect four MCP servers to one
model and let it pick. There is no router call and no per-workspace sub-agent — the host
sees `<workspace>__execute_query` for each workspace and decides, by which tool it calls,
which workspaces the question needs.

## What is shared with the other two arms, and where flat differs

Flat routes *by tool choice*, so it cannot run `orchestrator.plan` — choosing workspaces up
front is exactly what this arm does not do. Everything that does not depend on that is the
same code:

    stage                    a2a / mcp (nested)              mcp-flat
    routing + decomposition  plan(): one call, sub-question  NONE: the host picks tools; no
                             per workspace                   sub-questions exist
    tool loop                - / mcp.lane.tool_loop          mcp.lane.tool_loop (same)
    tools per workspace      - / DEFAULT_TOOLS               DEFAULT_TOOLS, namespaced
    per-workspace Answer     lane / mcp.lane.build_answer    mcp.lane.build_answer (same)
    deterministic checks     checks.run_checks               checks.run_checks (same)
    merge prose              merge(): a second model call    THE HOST'S OWN ANSWER, no
                                                             second call
    provenance + fallback    check_provenance,               the same two functions,
                             separate_answers                same rule
    payload                  orchestrator.run.Run            orchestrator.run.Run

So the two differences are the two things that *define* flat: no router, and the model that
routed is the model that writes the answer. If the checks refuse a pair, the host's prose is
replaced by the separate answers exactly as nested refuses — flat is not allowed to assert a
link the code has ruled out just because its own prose already did.

## The disambiguation risk this arm exists to show

In nested, a sub-agent only ever sees its own workspace's catalogue, so it *cannot* use a
metric id from another workspace. Flat holds every catalogue at once. `cross_workspace` counts
`execute_query` calls on workspace A whose metric ids were discovered only in another
workspace — the "picked a metric from the wrong workspace" case of AC 9, made countable.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

from gd_agents.lane import Answer
from gd_agents.mcp.client import DEFAULT_TOOLS, MCPClient, MCPError
from gd_agents.mcp.lane import MAX_TURNS, SYSTEM_PROMPT, build_answer, catalog_chars, tool_loop
from gd_agents.mcp.tools import anthropic_tools, load_definitions
from gd_agents.orchestrator.checks import check_provenance, model_check_prompt, run_checks
from gd_agents.orchestrator.fanout import FanoutReport
from gd_agents.orchestrator.merge import Merged, separate_answers
from gd_agents.orchestrator.plan import DEFAULT_MODEL, MODEL_ENV, Plan, Step, make_client
from gd_agents.orchestrator.run import Run
from gd_agents.registry import Registry
from gd_agents.transport import Host

#: Nested gives each lane sixteen turns and runs lanes in parallel. The flat host does every
#: workspace's discovery in one sequential loop, so it gets two lanes' worth — enough for the
#: two-workspace questions in the script. Not more: a budget large enough to never bind would
#: hide the cost this arm is measuring.
FLAT_MAX_TURNS = MAX_TURNS * 2

#: Tool names must match `^[a-zA-Z0-9_-]{1,64}$`.
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
SEPARATOR = "__"

#: An object id as tools return it and queries use it.
_IDENTIFIER = re.compile(r"\bmetric/[A-Za-z0-9_.\-]+")

FLAT_PREAMBLE = """\
You answer one analytical question that may need **several** GoodData workspaces. Each
workspace is a separate product with its own data model; they share no metrics, and nothing
can be joined across them.

Every tool name is prefixed with the workspace it acts on: `<workspace>{separator}<tool>`.
An identifier returned by one workspace's tools means nothing in another, even when the
title is the same. Use a workspace's identifiers only with that workspace's tools.

The workspaces:

{workspaces}

Use as few workspaces as will answer the question. If you cannot say what a workspace would
contribute, do not call its tools.

Within each workspace, work like this:

{lane_prompt}

When you write the final answer:

- **You may not compute across workspaces.** Compare, rank, sequence and narrate, but every
  number you write must appear verbatim in a tool result. Never add, subtract, divide or
  average values that came from different workspaces.
- Say which workspace each part came from. Name it.
- If the workspaces were queried over different periods or breakdowns, do not assert a
  connection: report each separately and say why.
- Also judge these yourself, and say so if either is a problem:
{model_checks}
"""


def tool_name(workspace: str, tool: str, index: int) -> str:
    """`<workspace>__<tool>`, falling back to `ws<index>__<tool>` past the 64-char limit."""
    name = f"{_UNSAFE.sub('_', workspace)}{SEPARATOR}{tool}"
    return name if len(name) <= 64 else f"ws{index}{SEPARATOR}{tool}"


def system_prompt(registry: Registry) -> str:
    """The flat host's prompt: the router's view of the workspaces, the nested sub-agent's
    tool guidance verbatim (minus its "one workspace" opening line), and the merge rules."""
    _, lane_body = SYSTEM_PROMPT.split("\n\n", 1)
    return FLAT_PREAMBLE.format(
        separator=SEPARATOR,
        workspaces=registry.prompt_block(),
        lane_prompt=lane_body.strip(),
        model_checks="\n".join(f"  {line}" for line in model_check_prompt().splitlines()),
    )


@dataclass
class FlatStats:
    """What the flat host did that the Run payload does not carry."""

    turns: int = 0
    calls: dict[str, int] = field(default_factory=dict)
    """Tool calls per workspace."""

    queried: list[str] = field(default_factory=list)
    """Workspaces the host ran `execute_query` against, in first-call order. A workspace it
    only searched and then left alone was considered, not used — and counting it as a lane
    would fail `lane_completeness` for a decision the host was right to make."""

    cross_workspace: int = 0
    """`execute_query` calls using a metric id discovered only in a *different* workspace."""

    error: str | None = None
    text: str = ""
    """The host's own final prose, kept even when the gates replace it in the reply."""


@dataclass
class FlatHost:
    """One model, every workspace's tools, one loop."""

    host: Host
    registry: Registry
    tools: tuple[str, ...] = DEFAULT_TOOLS
    definitions: dict[str, Any] | None = None
    client: Any | None = None
    model: str | None = None
    timeout: float = 120.0
    max_turns: int = FLAT_MAX_TURNS
    last: FlatStats = field(default_factory=FlatStats)

    def _model(self) -> tuple[Any, str]:
        caller: Any = self.client
        model = self.model
        if caller is None:
            caller, resolved = make_client()
            model = model or resolved
        return caller, model or os.environ.get(MODEL_ENV, DEFAULT_MODEL)

    def toolset(self) -> tuple[list[dict[str, Any]], dict[str, tuple[str, str]]]:
        """Every workspace's tools, namespaced, and the map back to `(workspace, tool)`."""
        definitions = self.definitions if self.definitions is not None else load_definitions()
        base = anthropic_tools(definitions, self.tools)
        tools: list[dict[str, Any]] = []
        route: dict[str, tuple[str, str]] = {}
        for index, entry in enumerate(self.registry.entries):
            for spec in base:
                name = tool_name(entry.id, spec["name"], index)
                route[name] = (entry.id, spec["name"])
                tools.append(
                    {
                        "name": name,
                        "description": f"[workspace {entry.id} — {entry.title}] {spec['description']}",
                        "input_schema": spec["input_schema"],
                    }
                )
        return tools, route

    def ask(self, question: str) -> Run:
        started = time.monotonic()
        caller, model = self._model()
        tools, route = self.toolset()
        clients: dict[str, MCPClient] = {}
        discovered: dict[str, set[str]] = {}
        stats = FlatStats()

        def dispatch(name: str, arguments: dict[str, Any]) -> tuple[str, str, str]:
            if name not in route:
                return "", name, f"ERROR: {name!r} is not a tool offered here."
            workspace, tool = route[name]
            mcp = clients.setdefault(
                workspace,
                MCPClient(host=self.host, workspace=workspace, tools=self.tools, timeout=self.timeout),
            )
            stats.calls[workspace] = stats.calls.get(workspace, 0) + 1
            if tool == "execute_query":
                if workspace not in stats.queried:
                    stats.queried.append(workspace)
                used = set(_IDENTIFIER.findall(json.dumps(arguments)))
                own = discovered.get(workspace, set())
                elsewhere = set().union(*(ids for ws, ids in discovered.items() if ws != workspace))
                if used & (elsewhere - own):
                    stats.cross_workspace += 1
            try:
                output = mcp.call(tool, **arguments)
            except MCPError as failure:
                output = f"ERROR: {failure}"
            if tool != "execute_query":
                discovered.setdefault(workspace, set()).update(_IDENTIFIER.findall(output))
            return workspace, tool, output

        history: list[dict[str, Any]] = [{"role": "user", "content": question}]
        loop = tool_loop(
            caller=caller,
            model=model,
            system=system_prompt(self.registry),
            tools=tools,
            history=history,
            dispatch=dispatch,
            max_turns=self.max_turns,
        )
        stats.turns = loop.turns
        stats.text = loop.text
        stats.error = loop.error
        if not loop.settled and loop.error is None:
            stats.error = f"no answer within {self.max_turns} model turns"
        self.last = stats
        elapsed = int((time.monotonic() - started) * 1000)

        # One Answer per workspace the host queried, in registry order, built by the same
        # function the nested lane uses. Its text is the rows themselves: there is no
        # per-workspace prose in flat, and the separate-answers fallback needs something true.
        touched = [entry.id for entry in self.registry.entries if entry.id in stats.queried]
        answers: list[Answer] = []
        for workspace in touched:
            runs = [(query, rows) for ws, query, rows in loop.runs if ws == workspace]
            answer = build_answer(
                workspace=workspace,
                question=question,
                text="",
                runs=runs,
                settled=True,
                population=f"mcp-flat: {stats.calls.get(workspace, 0)} tool call(s) from the host",
                latency_ms=elapsed,
                round_trips=stats.calls.get(workspace, 0),
                tokens=(0, 0),
                catalog_chars=catalog_chars(clients[workspace].calls),
            )
            answers.append(_with_rows_as_text(answer))

        run = Run(question=question)
        run.plan = Plan(
            question=question,
            steps=tuple(Step(workspace=ws, question=question, why="chosen by tool call") for ws in touched),
            reasoning="mcp-flat: no router; the host chose workspaces by the tools it called.",
        )
        run.lanes = FanoutReport(answers=tuple(answers), wall_ms=elapsed)
        run.merged = _merge(question, tuple(answers), loop.text, stats.error)
        # The host is router, analyst and merger in one context: all of it is orchestrator spend.
        run.merged.tokens_in, run.merged.tokens_out = loop.tokens_in, loop.tokens_out
        run.total_ms = int((time.monotonic() - started) * 1000)
        return run


def _with_rows_as_text(answer: Answer) -> Answer:
    from dataclasses import replace

    from gd_agents.artifacts import chart_pairs

    lines = []
    for _, data in chart_pairs(answer.artifacts):
        for row in (data or {}).get("formattedRows") or []:
            lines.append("; ".join(f"{key}: {value}" for key, value in row.items()))
    text = "Rows returned: " + " | ".join(lines[:30]) if lines else ""
    shape = replace(answer.shape, returned_data=bool(lines))
    return replace(answer, text=text, shape=shape)


def _merge(question: str, answers: tuple[Answer, ...], text: str, error: str | None) -> Merged:
    """The nested arm's gates, applied to the host's own prose instead of a merge call."""
    checks = run_checks(list(answers))
    merged = Merged(answers=answers, checks=checks, combinable=checks.combinable())
    if error:
        merged.text = separate_answers(question, answers, checks) if answers else text
        merged.rejected = f"host loop: {error}"
        merged.combinable = False
        return merged
    if not any(a.shape.returned_data for a in answers):
        merged.text = text
        merged.combinable = False
        merged.rejected = "the host returned no rows from any workspace"
        return merged
    if not checks.combinable():
        merged.text = separate_answers(question, answers, checks)
        return merged
    merged.provenance = check_provenance(text, list(answers))
    if not merged.provenance.ok():
        merged.rejected = merged.provenance.as_result().reason
        merged.text = separate_answers(question, answers, checks)
        merged.combinable = False
        return merged
    merged.text = text
    return merged
