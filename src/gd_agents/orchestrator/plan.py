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
from collections.abc import Sequence
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

4. **If you intend to combine the answers, ask for them in the same shape.** This is the
   rule most easily got wrong, and getting it wrong wastes the whole turn:

   - Every sub-question must state the *same* time period, in the same words. If a wider
     window is needed to see a change, widen it for every workspace, not one.
   - Every sub-question must ask for the breakdown you named in `combine_on`. If you plan to
     combine on month, each workspace must be asked "by month" — a ranking by campaign and a
     trend by month have nothing to join on, however well each answers on its own.
   - You may ask one workspace for two things ("by month, and also ranked by campaign") when
     the reader needs both. Asking each for a different one is what cannot be merged.

   Answers whose periods or breakdowns disagree are refused downstream and reported side by
   side, which is an honest outcome and a worse one.

5. **Before deciding that two answers cannot be combined, try time.** Every workspace
   measures over time, so a shared time grain is almost always available even when nothing
   else is. When a question asks whether two things moved together, influenced each other,
   or explain each other, and the workspaces share no business key:

   - Ask each workspace for its measure **by month** (or by week or quarter — the same one
     for all of them) over **the same window**, and set `combine_on` to that grain.
   - Where the reader also needs a ranking — "the campaigns we spent most on" — ask that
     workspace for *both*: the ranking and the same monthly series. One workspace can be
     asked two things; two workspaces cannot each be asked a different one.
   - Only set `combine_on` to null when even a shared time grain would not help, for example
     when the two answers are about different periods because the *user* asked for different
     periods.

   Reporting side by side is a real outcome and sometimes the only true one. It is not a
   shortcut to reach for when a common time grain was there to be asked for.

6. **A follow-up is routed on what it refers to.** Where a conversation is given, "those",
   "that one", "the same period" and "any of that" point at an earlier turn, and the
   sub-question you write must name what they point at — the workspace agent cannot read
   your mind, and a sub-question containing a dangling pronoun is unanswerable.

   The earlier turn tells you what is being referred to. It does **not** tell you where to
   route: "and did any of that show up in customer satisfaction?" follows a marketing turn
   and belongs to customer. Decide the route from this question, every time.

   Never answer with an empty workspace list because a question looks contextless. If it
   refers to an earlier turn, resolve the reference and route it.

7. **A question about the conversation itself needs no workspace.** Return an empty list for
   these and only these: "summarise what we have established", "what did you just tell me",
   "which of those answers was least certain", "where should we be looking". They ask about
   what has already been *said*.

   This is a narrow exception and easy to over-apply. A question naming a metric, a period, a
   breakdown or a comparison is an analytical question and **must be routed**, even where a
   previous turn happened to fetch something similar — "which month had the biggest gap
   between the two?" is a new question about the data, not a question about the conversation.
   When in doubt, route it.

   The exception applies only where a conversation is given. A question with no history
   behind it is never answerable this way.

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


@dataclass(frozen=True)
class Prior:
    """One earlier turn, as the router needs to see it.

    Deliberately thin: what was asked, which workspaces answered, and enough of the reply to
    resolve a reference. Not the sub-questions, and not the shapes — the router is being
    given the conversation so it can understand *this* question, not a plan to copy.
    """

    question: str
    workspaces: tuple[str, ...] = ()
    reply: str = ""


#: How much of an earlier reply the router sees. Enough to resolve "the top one" against the
#: thing that was actually top; short enough that four turns do not crowd out the registry.
REPLY_EXCERPT = 700

#: Turns kept. A reference reaching further back than this is rare, and every turn kept is
#: tokens spent on every subsequent question.
HISTORY_TURNS = 4


def history_block(history: Sequence[Prior]) -> str:
    kept = list(history)[-HISTORY_TURNS:]
    if not kept:
        return ""
    lines = ["Conversation so far, oldest first:"]
    for number, turn in enumerate(kept, start=1):
        lines.append(f"\n[{number}] user asked: {turn.question}")
        if turn.workspaces:
            lines.append(f"    answered by: {', '.join(turn.workspaces)}")
        if turn.reply:
            excerpt = " ".join(turn.reply.split())[:REPLY_EXCERPT]
            lines.append(f"    the answer given: {excerpt}")
    return "\n".join(lines) + "\n\n"


def user_prompt(question: str, registry: Registry, history: Sequence[Prior] = ()) -> str:
    return (
        f"Workspaces available to this caller:\n\n{registry.prompt_block()}\n\n"
        f"{history_block(history)}"
        f"User question: {question}"
    )


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
        # `AnthropicBedrock` is present only when the SDK's bedrock extra is installed, and
        # the SDK does not re-export it from the package root in a way a type checker sees.
        # Fetching it by name means asking for Bedrock without it fails with a sentence a
        # reader can act on rather than an AttributeError.
        constructor = getattr(anthropic, "AnthropicBedrock", None)
        if constructor is None:
            raise PlanError(
                f"${BEDROCK_MODEL_ENV} is set but this anthropic install has no Bedrock "
                "client. Install anthropic with its bedrock extra, or unset the variable "
                "and use $ANTHROPIC_API_KEY."
            )
        return constructor(), bedrock
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise PlanError(f"No ANTHROPIC_API_KEY and no ${BEDROCK_MODEL_ENV}.")
    return anthropic.Anthropic(), os.environ.get(MODEL_ENV, DEFAULT_MODEL)


def plan(
    question: str,
    registry: Registry,
    *,
    client: Any | None = None,
    model: str | None = None,
    history: Sequence[Prior] = (),
) -> Plan:
    """Route and decompose, in one call.

    `history` is the conversation so far. Without it a follow-up cannot be routed at all:
    measured on 2026-09-22, "which of them converted best?" made the router return an empty
    plan with the reasoning "there is no prior context" — correct, and useless. Nine of
    thirty-five scripted turns failed that way.

    Giving the router the conversation is **not** the same as reusing the route. Every turn
    still plans from scratch; it simply knows what "them" means. A session that reused the
    previous selection would answer "and did any of that show up in customer satisfaction?"
    from marketing, confidently and from the wrong place.
    """
    # Bound to its own name rather than reassigning the parameter: a checker keeps the
    # parameter's declared `Any | None` past the guard and then reports `.messages` on None.
    caller: Any = client
    if caller is None:
        caller, resolved = make_client()
        model = model or resolved
    if not model:
        model = os.environ.get(MODEL_ENV, DEFAULT_MODEL)

    response = caller.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt(question, registry, history)}],
    )

    text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
    result = parse_plan(question, text, registry)
    usage = getattr(response, "usage", None)
    result.tokens_in = int(getattr(usage, "input_tokens", 0) or 0)
    result.tokens_out = int(getattr(usage, "output_tokens", 0) or 0)
    return result
