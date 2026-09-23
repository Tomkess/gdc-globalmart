"""One workspace, reached over MCP. An implementation of `Lane`, and it is not short.

This module is the comparison's finding, not its plumbing.

`a2a/client.py` sends an English sentence and reads the answer: metric resolution, MAQL,
filter choice and chart selection all happen inside the workspace, against a model that
already knows the semantic layer. There is no catalogue to hold and no loop to run.

MCP offers **tools**. Something still has to do that reasoning, so this module builds a
per-workspace sub-agent: a system prompt, that workspace's five tools, and a loop that
resolves identifiers, writes a query, runs it and turns rows into an answer. Conforming to
the same `Lane` interface is exactly what costs MCP the extra work — which is why the
interface lives in `lane.py` and not inside either protocol package.

**To federate over MCP you must build what A2A hands you for free.** The difference in
length between this file and `a2a/client.py` is the most honest single number in FEAT-014.

## Keeping the arms comparable

Everything above the lane is identical — the same router, the same decomposition, the same
eight merge checks, the same merge prompt, the same question script. A comparison whose
orchestrator differs between the arms measures the orchestrator.

Two things this lane must produce for that to hold:

**A `Shape`.** The merge checks need grain, window and filters, or they return UNKNOWN on
every answer and the MCP arm would appear to "combine" more readily by being less checkable.
The sub-agent's `execute_query` call carries all three in its AAC query, so the shape is read
from the query it actually ran — the same source of truth as the A2A artifact.

**Artifacts.** The rows are shaped into the same `visualization` / `visualization-data`
DataParts the A2A lane returns, so the viewer, the aligned table and `numbers` all work
unchanged. This is presentation parity, not invention: every value comes from the rows the
workspace returned.

## What is counted

`round_trips` is model turns, and under MCP that is where the cost concentrates. `tokens_in`
and `tokens_out` are the sub-agent's own — under A2A this number does not exist, because the
workspace pays it. That is not MCP being worse; it is the bill moving to whoever runs the
orchestrator, and the recommendation has to say which side of that line a customer is on.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from gd_agents.artifacts import grain_of, window_of
from gd_agents.lane import Answer, Shape
from gd_agents.mcp.client import DEFAULT_TOOLS, MCPClient, MCPError
from gd_agents.mcp.tools import anthropic_tools, load_definitions
from gd_agents.orchestrator.events import Observer, emit
from gd_agents.orchestrator.plan import DEFAULT_MODEL, MODEL_ENV, make_client
from gd_agents.transport import Host

#: Turns before the loop gives up.
#:
#: Was eight, on the reasoning that the documented flow is discover-then-execute and a lane
#: that has not answered in eight is not one turn from doing so. Measurement disagreed twice:
#: one question answered correctly on the **eleventh** turn, and two more hit the ceiling
#: mid-recovery with the right identifiers already in hand. The documented flow is two turns;
#: the observed flow is two turns plus however many it takes to get a filter past the schema.
#:
#: Sixteen, then — and the number itself is a finding. Under A2A this budget does not exist,
#: because the workspace agent resolves all of it server-side in one round trip.
MAX_TURNS = 16

MAX_TOKENS = 4000

SYSTEM_PROMPT = """\
You answer one analytical question about **one** GoodData workspace, using the tools given.

You have no knowledge of this workspace's contents. Everything — which metrics exist, what
they are called, which attributes they can be broken down by — has to come from the tools.

The efficient order, and the one to prefer:

1. `ai_search` with the question in plain language. It returns the metrics, attributes and
   existing visualizations that match, ranked, with their identifiers. This is almost always
   enough, and it is far cheaper than listing.
2. Only if `ai_search` leaves you without an identifier you need, `list_workspace_metrics` or
   `list_workspace_attributes` — and pass `rsql_filter` or `limit` when you can. An unfiltered
   listing can return tens of thousands of tokens.
3. `execute_query` with the identifiers you resolved. Typed identifiers (`metric/...`,
   `label/...`) in `using`; bare local keys in sorts and ranking filters.

**Use identifiers exactly as a tool returned them.** `ai_search` gives you the real id —
`metric/average_total_nps_score`. Do not reconstruct one from a title or a pattern you have
seen elsewhere; an invented id fails with "objects are either inaccessible or not existing",
and it is indistinguishable from the object genuinely not being there.

**Filtering by date has exactly two forms, and both need `using`:**

    absolute  {"type": "date_filter", "using": "dataset/<date dataset>",
               "from": "2026-04-01", "to": "2026-06-30"}      full YYYY-MM-DD, strings

    relative  {"type": "date_filter", "using": "dataset/<date dataset>",
               "granularity": "MONTH", "from": -3, "to": -1}  whole periods back, integers

`from`/`to` are strings in the first and integers in the second — mixing them fails
validation, and so does omitting `using`. The date *dataset* goes in `using`
(`dataset/transaction_date`); the date *label* goes in `fields` for the breakdown
(`label/transaction_date.month`). They are different things and both are usually needed.

Then answer in prose, for a reader. State the numbers you actually got. Name the metric by
its title rather than its identifier. Say the period and the breakdown you used.

If the data does not answer the question, say so plainly and say what is missing. Never
invent a number, a metric or an identifier: every value in your answer must come from a
tool result you received.
"""


def _tool_text(result: Any) -> str:
    return result if isinstance(result, str) else json.dumps(result)


@dataclass
class MCPLane:
    """One workspace, asked in English — with the analyst built here rather than there."""

    host: Host
    workspace: str
    description: str = ""
    tools: tuple[str, ...] = DEFAULT_TOOLS
    timeout: float = 120.0
    max_turns: int = MAX_TURNS
    client: Any | None = None
    """An Anthropic client. The sub-agent's model, not the orchestrator's — though it is the
    same one, so the token numbers are comparable."""

    model: str | None = None
    definitions: dict[str, Any] | None = None
    observe: Observer | None = None
    contexts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    """Per-conversation message history. A2A gets this from the server via `contextId`; here
    it is ours to keep, which is one more thing the protocol does not do for us."""

    def describe(self) -> str:
        return self.description

    def _step(self, step: str, detail: str = "", **extra: Any) -> None:
        emit(self.observe, "lane_step", workspace=self.workspace, step=step, detail=detail, **extra)

    def _model(self) -> tuple[Any, str]:
        caller: Any = self.client
        model = self.model
        if caller is None:
            caller, resolved = make_client()
            model = model or resolved
        return caller, model or os.environ.get(MODEL_ENV, DEFAULT_MODEL)

    def ask(self, question: str, *, context_id: str | None = None) -> Answer:
        started = time.monotonic()
        mcp = MCPClient(host=self.host, workspace=self.workspace, tools=self.tools, timeout=self.timeout)
        definitions = self.definitions if self.definitions is not None else load_definitions()
        caller, model = self._model()

        history = list(self.contexts.get(context_id or "", [])) if context_id else []
        history.append({"role": "user", "content": question})

        tokens_in = tokens_out = 0
        turns = 0
        text = ""
        settled = False
        """Whether the loop ended because the model stopped asking for tools — the only way
        a turn is finished. Running out of turns leaves `text` holding whatever the model was
        thinking mid-way, which reads like an answer and is not one. That is the same mistake
        the A2A lane makes if it reads `history` instead of `status.message`."""

        error: str | None = None
        # Query and result together, appended in the same breath. Keeping two lists and
        # indexing across them is what produced the first version of this bug: a query that
        # failed still landed in `queries`, every later result paired with the wrong query,
        # and the answer's grain came from a query that returned nothing.
        runs: list[tuple[dict[str, Any], dict[str, Any]]] = []

        self._step("mcp/loop", f"{len(self.tools)} tools, up to {self.max_turns} turns")

        while turns < self.max_turns:
            turns += 1
            try:
                response = caller.messages.create(
                    model=model,
                    max_tokens=MAX_TOKENS,
                    system=SYSTEM_PROMPT,
                    tools=anthropic_tools(definitions, self.tools),
                    messages=history,
                )
            except Exception as failure:  # noqa: BLE001 - a lane never raises upward
                error = f"{type(failure).__name__}: {failure}"[:300]
                break

            usage = getattr(response, "usage", None)
            tokens_in += int(getattr(usage, "input_tokens", 0) or 0)
            tokens_out += int(getattr(usage, "output_tokens", 0) or 0)

            blocks = list(response.content)
            text = "".join(b.text for b in blocks if getattr(b, "type", "") == "text").strip() or text
            requests = [b for b in blocks if getattr(b, "type", "") == "tool_use"]
            if not requests:
                settled = True
                break

            history.append({"role": "assistant", "content": [_as_dict(b) for b in blocks]})
            results = []
            for request in requests:
                arguments = dict(request.input or {})
                try:
                    output = mcp.call(request.name, **arguments)
                    if request.name == "execute_query" and isinstance(arguments.get("query"), dict):
                        parsed = _parse_rows(output)
                        if "error" not in parsed:
                            runs.append((arguments["query"], parsed))
                except MCPError as failure:
                    # Including a tool outside the set, which is refused before any request
                    # is made — so there may be no recorded call to read a latency from.
                    output = f"ERROR: {failure}"
                last = mcp.calls[-1] if mcp.calls else None
                self._step(
                    request.name,
                    f"{len(output):,} chars",
                    latency_ms=last.latency_ms if last else 0,
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": request.id,
                        "content": _tool_text(output)[:60_000],
                    }
                )
            history.append({"role": "user", "content": results})

        if not settled and error is None:
            # Whatever is in `text` is a mid-loop thought, not a reply. Kept, because it says
            # what the sub-agent was stuck on, but the lane reports failure and the merge
            # treats it as a lane that did not contribute.
            error = (
                f"no answer within {self.max_turns} model turns; "
                f"{mcp.round_trips()} tool call(s) made"
            )

        if context_id:
            self.contexts[context_id] = history

        elapsed = int((time.monotonic() - started) * 1000)
        artifacts = _artifacts(runs, question)
        shape = _shape([query for query, _ in runs])
        self._step(
            "read",
            f"{mcp.round_trips()} tool call(s), {mcp.chars_in() // 4:,} tok of context",
            latency_ms=elapsed,
        )

        from gd_agents.a2a.client import numbers_from_artifacts, numbers_in

        return Answer(
            workspace=self.workspace,
            question=question,
            text=text,
            shape=Shape(
                grain=shape.grain,
                grains=shape.grains,
                time_from=shape.time_from,
                time_to=shape.time_to,
                windows=shape.windows,
                filters=shape.filters,
                population=f"mcp: {mcp.round_trips()} tool call(s), {turns} model turn(s)",
                returned_data=settled and bool(text) and bool(runs),
            ),
            numbers=tuple(dict.fromkeys(numbers_from_artifacts(artifacts) + numbers_in(text))),
            artifacts=artifacts,
            latency_ms=elapsed,
            round_trips=turns,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            context_id=context_id,
            error=error,
        )


def _as_dict(block: Any) -> dict[str, Any]:
    """One content block as the API wants it echoed back."""
    kind = getattr(block, "type", "")
    if kind == "text":
        return {"type": "text", "text": block.text}
    return {"type": "tool_use", "id": block.id, "name": block.name, "input": dict(block.input or {})}


def _parse_rows(output: str) -> dict[str, Any]:
    """`execute_query`'s result, as data. Unparseable output is not silently dropped."""
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return {"error": output[:300]}
    return parsed if isinstance(parsed, dict) else {"rows": parsed}


def _shape(queries: list[dict[str, Any]]) -> Shape:
    """The shape of what was actually run, read from the AAC queries the sub-agent sent.

    The same rules the A2A lane applies to the `visualization` artifact, against the same
    query language — so `shared_dimension` and `time_window_match` compare like with like
    across the two arms rather than comparing our two readings of them.
    """
    grains: list[str] = []
    windows: list[str] = []
    filters: list[str] = []
    for query in queries:
        as_visualization = {"query": query, "view_by": _view_by(query)}
        if grain := grain_of(as_visualization):
            grains.append(grain)
        if window := window_of(as_visualization):
            windows.append(window)
        for name, spec in (query.get("filter_by") or {}).items():
            if isinstance(spec, dict) and spec.get("type") != "date_filter":
                filters.append(f"{name}={spec.get('type') or 'filter'}")

    grain_set = tuple(dict.fromkeys(grains))
    window_set = tuple(dict.fromkeys(windows))
    window = window_set[0] if window_set else None
    return Shape(
        grain=grain_set[0] if grain_set else None,
        grains=grain_set,
        time_from=window,
        time_to=window,
        windows=window_set,
        filters=tuple(sorted(set(filters))),
    )


def _view_by(query: dict[str, Any]) -> list[str]:
    """Which of a query's fields are the breakdown.

    An AAC query does not separate them the way a `visualization` artifact does, so they are
    recovered the same way the workspace would: a field resolving to a `label/` or
    `dataset/` reference is a dimension, one resolving to `metric/` or `fact/` is not.
    """
    dimensions = []
    for key, field_spec in (query.get("fields") or {}).items():
        using = field_spec.get("using") if isinstance(field_spec, dict) else field_spec
        if isinstance(using, str) and using.startswith(("label/", "dataset/", "attribute/")):
            dimensions.append(str(key))
    return dimensions


def _artifacts(
    runs: list[tuple[dict[str, Any], dict[str, Any]]], question: str
) -> tuple[dict[str, Any], ...]:
    """The rows, in the DataPart shape the A2A lane returns.

    Presentation parity rather than invention: the viewer, the aligned table and provenance
    all read these, and an MCP answer that could not be rendered would look worse than it is
    for a reason that has nothing to do with the protocol.

    A result whose shape is not recognised yields **no artifact at all**. That is the whole
    lesson of the first version: it guessed, and a guess here does not fail visibly — it
    renders a table of real numbers under the wrong headings, which is worse than an empty
    panel by a wide margin.
    """
    built: list[dict[str, Any]] = []
    for index, (query, result) in enumerate(runs):
        columns, rows, formatted = _read_xtab(result)
        if not columns or not rows:
            continue
        identifier = f"mcp_{index}"
        dimensions = _view_by(query)
        built.append(
            {
                "name": "visualization",
                "data": {
                    "id": identifier,
                    "type": "table",
                    "title": question[:120],
                    "view_by": dimensions,
                    "metrics": [k for k in (query.get("fields") or {}) if k not in dimensions],
                    "query": query,
                },
            }
        )
        built.append(
            {
                "name": "visualization-data",
                "data": {
                    "visualizationId": identifier,
                    "columns": columns,
                    "rows": rows,
                    "formattedRows": formatted,
                    "rowCount": len(rows),
                    "truncated": bool(result.get("truncated")),
                },
            }
        )
    return tuple(built)


def _read_xtab(
    result: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """`execute_query`'s xtab result: columns, plus two parallel arrays of values.

    The shape, measured 2026-09-23:

        columns        [{name, type: attribute|metric, format?}]  attributes first
        row_labels     [["2026-04"], ["2026-05"], ...]            the attribute values
        data           [[11944.45], [9726.62], ...]               the metric values
        formatted_data [["11,944.45"], ["9,726.62"], ...]         as the workspace formats them

    The labels and the values are **separate arrays**, which is what the first version of
    this function missed: it zipped the column names against the metric row, so `Month/Year`
    took the first metric's value, every metric shifted one place left, and the last one
    vanished. The table rendered, the numbers were real, and every one of them was under the
    wrong heading.

    So the widths are checked rather than assumed. A row that does not carry exactly as many
    labels as there are attribute columns, and as many values as there are metric columns, is
    a shape this function does not understand — and it returns nothing rather than something.
    """
    columns = result.get("columns")
    labels = result.get("row_labels")
    values = result.get("data")
    formatted_values = result.get("formatted_data") or values
    if not (isinstance(columns, list) and isinstance(labels, list) and isinstance(values, list)):
        return [], [], []

    attribute_names = [
        str(c.get("name")) for c in columns if isinstance(c, dict) and c.get("type") == "attribute"
    ]
    metric_names = [
        str(c.get("name")) for c in columns if isinstance(c, dict) and c.get("type") != "attribute"
    ]
    if not metric_names:
        return [], [], []

    def build(value_rows: list[Any]) -> list[dict[str, Any]] | None:
        out: list[dict[str, Any]] = []
        for label_row, value_row in zip(labels, value_rows, strict=False):
            if not isinstance(label_row, list) or not isinstance(value_row, list):
                return None
            if len(label_row) != len(attribute_names) or len(value_row) != len(metric_names):
                return None
            row: dict[str, Any] = dict(zip(attribute_names, label_row, strict=True))
            row.update(dict(zip(metric_names, value_row, strict=True)))
            out.append(row)
        return out

    rows = build(values)
    formatted = build(formatted_values if isinstance(formatted_values, list) else values)
    if rows is None or formatted is None or not rows:
        return [], [], []
    return [dict(c) for c in columns if isinstance(c, dict)], rows, formatted
