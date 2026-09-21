"""One model call: which workspaces, and what to ask each one.

The routing half is the obvious part. The decomposition half is what makes this federation
rather than broadcast — the orchestrator does not forward the user's question to every
chosen workspace, it writes a *different* sub-question per workspace, because each holds
only part of the answer in its own vocabulary:

    "Did the campaigns we spent most on actually move customer satisfaction?"
      -> marketing: "Show Total Campaign Spend by campaign for last quarter"
      -> customer:  "Show Average Total NPS Score by month for last quarter"

Neither workspace is asked the original question, because neither can answer it.

**Sub-questions must be specific enough not to trigger a clarification.** Measured on
2026-09-21: asked "what was total campaign spend last quarter?" the live agent replied
asking which spend metric was meant. An orchestrator cannot answer that — there is no human
in the lane — so a vague sub-question costs a round trip and returns nothing. Naming the
metric worked. The prompt says so explicitly, and the registry descriptions carry the metric
names that make it possible.

**The model must be able to choose one.** A router that always returns everything has not
routed, and calling four lanes when one would do costs four times the latency and tokens for
a worse answer.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from gd_agents.registry import Registry

DEFAULT_MODEL = "claude-opus-4-7"
MODEL_ENV = "ANTHROPIC_MODEL"
BEDROCK_MODEL_ENV = "ANTHROPIC_BEDROCK_MODEL"

MAX_TOKENS = 2000


class PlanError(Exception):
    """The plan could not be produced, or came back unusable."""


SYSTEM_PROMPT = """\
You route analytical questions across several GoodData workspaces and decompose them.

Each workspace is a separate product with its own data model. They share no metrics and
nothing can be joined across them. A workspace can only answer about what it measures.

Your job, for one user question:

1. Choose the workspaces that are needed. Choose as few as will answer the question.
   Choosing one is correct and common. Choosing all of them is almost always wrong — if you
   cannot say what a workspace would contribute, leave it out.

2. For each chosen workspace, write the sub-question to send to it. Rules:
   - Ask only what that workspace can answer, in its own vocabulary.
   - Name the metric explicitly, using the metric names given in its description. A vague
     sub-question makes the workspace agent stop and ask which metric was meant, and there
     is nobody to answer it.
   - State the time period and the breakdown explicitly ("by month", "for the last 6
     months") when the question implies one.
   - Never ask a workspace to compare against another workspace's data. It cannot see it.

3. Say what you expect to do with the answers — whether they can be combined and on what
   shared dimension, or whether they will have to be reported separately.

Reply with JSON only, no prose and no code fences:

{"workspaces": [{"id": "<workspace id>", "question": "<sub-question>", "why": "<one line>"}],
 "reasoning": "<why this set>",
 "combine_on": "<shared dimension, or null if they cannot be combined>"}
"""


@dataclass(frozen=True)
class Step:
    """One workspace and the sub-question written for it."""

    workspace: str
    question: str
    why: str = ""


@dataclass
class Plan:
    question: str
    steps: tuple[Step, ...] = ()
    reasoning: str = ""
    combine_on: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    raw: str = ""
    notes: list[str] = field(default_factory=list)
    """Anything corrected while parsing — a hallucinated workspace, a missing field."""

    def workspaces(self) -> tuple[str, ...]:
        return tuple(step.workspace for step in self.steps)

    def summary_lines(self) -> list[str]:
        lines = [f"question          : {self.question}", f"workspaces        : {len(self.steps)}"]
        for step in self.steps:
            lines.append(f"  {step.workspace}")
            lines.append(f"    ask  : {step.question}")
            if step.why:
                lines.append(f"    why  : {step.why}")
        lines.append(f"combine on        : {self.combine_on or 'not combinable'}")
        if self.notes:
            lines.append(f"notes             : {'; '.join(self.notes)}")
        return lines


def user_prompt(question: str, registry: Registry) -> str:
    return f"Workspaces available to this caller:\n\n{registry.prompt_block()}\n\nUser question: {question}"


def _strip_fences(text: str) -> str:
    """Models add code fences even when told not to. Cheaper to tolerate than to re-prompt."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[: -len("```")]
    return stripped.strip()


def parse_plan(question: str, raw: str, registry: Registry) -> Plan:
    """Turn the model's reply into a plan, discarding anything it invented.

    A workspace the caller cannot see must never be called, however confidently it was
    named — that is a routing error in the model, and silently dropping it without a note
    would hide it from the measurement.
    """
    plan = Plan(question=question, raw=raw)
    try:
        payload: Any = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as error:
        raise PlanError(f"plan was not JSON: {error}. Raw: {raw[:300]!r}") from error

    if not isinstance(payload, dict):
        raise PlanError(f"plan was not an object: {raw[:200]!r}")

    known = set(registry.ids())
    steps: list[Step] = []
    for item in payload.get("workspaces") or []:
        if not isinstance(item, dict):
            continue
        workspace = str(item.get("id") or "").strip()
        sub_question = str(item.get("question") or "").strip()
        if workspace not in known:
            plan.notes.append(f"dropped unknown workspace {workspace!r}")
            continue
        if not sub_question:
            plan.notes.append(f"dropped {workspace!r}: no sub-question")
            continue
        steps.append(Step(workspace=workspace, question=sub_question, why=str(item.get("why") or "")))

    if not steps:
        raise PlanError(f"plan chose no usable workspace. Raw: {raw[:300]!r}")

    plan.steps = tuple(steps)
    plan.reasoning = str(payload.get("reasoning") or "")
    combine = payload.get("combine_on")
    plan.combine_on = str(combine) if combine not in (None, "", "null") else None
    return plan


def make_client() -> tuple[Any, str]:
    """An Anthropic client and the model id, matching how the existing demos pick one."""
    try:
        import anthropic
    except ImportError as error:  # pragma: no cover - dependency is an extra
        raise PlanError("anthropic is not installed. Install the agents extra.") from error

    bedrock = os.environ.get(BEDROCK_MODEL_ENV, "")
    if bedrock:
        return anthropic.AnthropicBedrock(), bedrock
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise PlanError(f"No ANTHROPIC_API_KEY and no ${BEDROCK_MODEL_ENV}.")
    return anthropic.Anthropic(), os.environ.get(MODEL_ENV, DEFAULT_MODEL)


def plan(
    question: str,
    registry: Registry,
    *,
    client: Any | None = None,
    model: str | None = None,
) -> Plan:
    """Route and decompose, in one call."""
    if client is None:
        client, resolved = make_client()
        model = model or resolved
    if not model:
        model = os.environ.get(MODEL_ENV, DEFAULT_MODEL)

    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt(question, registry)}],
    )

    text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
    result = parse_plan(question, text, registry)
    usage = getattr(response, "usage", None)
    result.tokens_in = int(getattr(usage, "input_tokens", 0) or 0)
    result.tokens_out = int(getattr(usage, "output_tokens", 0) or 0)
    return result
