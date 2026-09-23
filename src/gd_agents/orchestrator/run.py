"""One question in, one attributed answer out. The whole orchestrator, in two functions.

`ask` is a single turn: plan, fan out, check, merge. `enrich` is the retry path — re-ask only
the lanes whose part is still missing, and merge the fresh answers against the ones already
held. A lane is lost on about 2% of turns — measured over 105 live turns — so that second
function is not an edge case across a conversation of any length.

Everything above this is the front end's business. Everything below is the protocol's. This
module is what FEAT-014 will call unchanged over MCP, which is why it takes lanes as an
argument rather than building them: a comparison whose orchestrator differs between the arms
measures the orchestrator.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from gd_agents.lane import Lane
from gd_agents.orchestrator.align import align, shared_grain
from gd_agents.orchestrator.events import Observer, emit
from gd_agents.orchestrator.fanout import FanoutReport, fanout
from gd_agents.orchestrator.merge import Merged, merge
from gd_agents.orchestrator.plan import Plan, PlanError, Step, plan
from gd_agents.orchestrator.session import Session, Turn
from gd_agents.registry import Registry


@dataclass
class Run:
    """Everything one turn did, for the reader and for the measurement."""

    question: str
    plan: Plan | None = None
    lanes: FanoutReport = field(default_factory=FanoutReport)
    merged: Merged = field(default_factory=Merged)
    total_ms: int = 0
    enriched: tuple[str, ...] = ()
    """Workspaces re-asked on this turn, empty for a first attempt."""

    def reply(self) -> str:
        return self.merged.text

    def tokens(self) -> tuple[int, int]:
        """Orchestrator tokens only — plan plus merge.

        Deliberately excludes what happens inside a workspace: that is the agent's cost and
        A2A does not report it. Under MCP the same work lands in *this* number, which is
        most of what the protocol comparison is about.
        """
        plan_in = self.plan.tokens_in if self.plan else 0
        plan_out = self.plan.tokens_out if self.plan else 0
        return (plan_in + self.merged.tokens_in, plan_out + self.merged.tokens_out)

    def aligned(self) -> dict[str, Any] | None:
        """The lanes' own series side by side on the grain they agreed on, or nothing.

        Offered only when the checks let the answer combine: a table of two series implies
        they are comparable, and that is precisely the claim the checks exist to gate. It is
        alignment on a shared key, never a join — see `align.py`.
        """
        if not self.merged.combinable:
            return None
        table = align(self.lanes.answers, shared_grain(self.lanes.answers))
        return table.payload() if table.usable() else None

    def payload(self) -> dict[str, Any]:
        """One turn as data, for a host to render however it likes.

        **This is the interface, not the page.** Infobip already has Portal Copilot, so what
        matters is what GoodData hands back and whether their host can use it — not how we
        draw it. Their team can read this shape and say in ten minutes whether their copilot
        can consume it, which is a better answer than any screenshot.

        Artifacts are passed through whole and uninterpreted. They are GoodData-specific
        DataParts: `visualization` carries a chart definition in GoodData's own query
        language, `visualization-data` carries rows. A host that is not GoodData's UI has to
        render that itself or ignore it — which is a real product question and is on the gap
        list.
        """
        return {
            "question": self.question,
            "reply": self.merged.text,
            "combinable": self.merged.combinable,
            "enriched": list(self.enriched),
            # The rows the merged answer was read off, aligned on the shared grain. Null
            # when the lanes do not combine, or when there is nothing to compare.
            "table": self.aligned(),
            # Lanes that stopped to ask something. A host with a human in front of it can
            # put the question to them and reply on that lane's own conversation; a host
            # without one ignores this and the lane simply did not contribute.
            "pending": [
                {"workspace": answer.workspace, "question": answer.question, "asks": answer.text}
                for answer in self.lanes.answers
                if answer.input_required
            ],
            "routing": {
                "workspaces": [
                    {"id": step.workspace, "question": step.question, "why": step.why}
                    for step in (self.plan.steps if self.plan else ())
                ],
                "reasoning": self.plan.reasoning if self.plan else "",
                "combine_on": self.plan.combine_on if self.plan else None,
                "notes": list(self.plan.notes) if self.plan else [],
            },
            "lanes": [
                {
                    "workspace": answer.workspace,
                    "question": answer.question,
                    "text": answer.text,
                    "ok": answer.ok(),
                    "returned_data": answer.shape.returned_data,
                    "input_required": answer.input_required,
                    "error": answer.error,
                    "latency_ms": answer.latency_ms,
                    "round_trips": answer.round_trips,
                    "grain": answer.shape.grain,
                    "window": answer.shape.time_from,
                    "filters": list(answer.shape.filters),
                    "source": answer.shape.population,
                    "numbers": list(answer.numbers),
                    "artifacts": [dict(artifact) for artifact in answer.artifacts],
                }
                for answer in self.lanes.answers
            ],
            "checks": [
                {"check": r.check, "verdict": r.verdict.value, "reason": r.reason}
                for r in self.merged.checks.results
            ],
            "provenance": {
                "ok": self.merged.provenance.ok(),
                "checked": self.merged.provenance.checked,
                "invented": list(self.merged.provenance.invented),
                "rejected": self.merged.rejected,
            },
            "timings": {
                "total_ms": self.total_ms,
                "fanout_wall_ms": self.lanes.wall_ms,
                "slowest_lane_ms": self.lanes.slowest_ms(),
            },
            "tokens": dict(zip(("in", "out"), self.tokens(), strict=True)),
        }

    def summary_lines(self) -> list[str]:
        tokens_in, tokens_out = self.tokens()
        lines = [f"question          : {self.question}"]
        if self.enriched:
            lines.append(f"enriched          : {', '.join(self.enriched)}")
        if self.plan:
            lines.append(f"routed to         : {', '.join(self.plan.workspaces())}")
            lines.append(f"combine on        : {self.plan.combine_on or 'not combinable'}")
        lines.extend(self.lanes.summary_lines())
        lines.extend(self.merged.summary_lines())
        lines.append(f"orchestrator tok  : {tokens_in:,} in / {tokens_out:,} out")
        lines.append(f"total             : {self.total_ms} ms")
        return lines


def _contexts(report: FanoutReport, previous: Mapping[str, str] | None = None) -> dict[str, str]:
    carried = dict(previous or {})
    for answer in report.answers:
        if answer.context_id:
            carried[answer.workspace] = answer.context_id
    return carried


def _from_memory(
    question: str,
    session: Session,
    run: Run,
    started: float,
    *,
    client: Any | None = None,
    model: str | None = None,
    observe: Observer | None = None,
) -> Run:
    """Answer from what the conversation already holds, calling no workspace.

    The closing move of most real threads — "so where should we actually be looking?" — asks
    about the conversation rather than for new data, and the router says so by choosing
    nothing. Fanning out anyway would spend four agent calls to re-fetch what is already in
    hand; erroring would fail a turn that is perfectly answerable.

    The same merge runs over the held answers, so the same rules apply: attribution stays,
    and provenance still refuses a number no lane produced.
    """
    held = session.held()
    emit(observe, "from_memory", lanes=[a.workspace for a in held])
    run.lanes = FanoutReport(answers=held)
    run.plan = Plan(
        question=question,
        steps=tuple(Step(workspace=a.workspace, question=a.question) for a in held),
        reasoning="No workspace was needed: answered from what this conversation already holds.",
    )
    run.merged = merge(question, held, client=client, model=model)
    session.remember(
        Turn(
            question=question,
            workspaces=tuple(a.workspace for a in held),
            reply=run.merged.text,
            answers=held,
            combinable=run.merged.combinable,
        )
    )
    run.total_ms = int((time.monotonic() - started) * 1000)
    emit(observe, "done", payload=run.payload())
    return run


def ask(
    question: str,
    registry: Registry,
    lanes: Mapping[str, Lane],
    *,
    session: Session | None = None,
    client: Any | None = None,
    model: str | None = None,
    inject_failure: str | None = None,
    observe: Observer | None = None,
) -> Run:
    """One turn: plan, fan out, check, merge.

    The route is recomputed every turn. A follow-up like "and did any of that show up in
    customer satisfaction?" needs a workspace the previous turn never touched, so reusing the
    earlier selection would answer the wrong question from the wrong place.

    `observe` is optional narration — see `events.py`. The payload is still the interface.
    """
    started = time.monotonic()
    session = session if session is not None else Session()
    run = Run(question=question)

    emit(observe, "planning", question=question, workspaces=list(registry.ids()))
    try:
        run.plan = plan(question, registry, client=client, model=model, history=session.prior())
    except PlanError:
        # A question that needs no workspace is a real turn, not a failure — "summarise what
        # we have established" asks about the conversation, and the conversation is here.
        # Only ever after a turn that did fetch something: with nothing held, an empty plan
        # is the router failing and must be reported as one.
        if not session.held():
            raise
        return _from_memory(question, session, run, started, client=client, model=model, observe=observe)
    emit(
        observe,
        "plan",
        workspaces=[
            {"id": step.workspace, "question": step.question, "why": step.why}
            for step in run.plan.steps
        ],
        reasoning=run.plan.reasoning,
        combine_on=run.plan.combine_on,
        notes=list(run.plan.notes),
        tokens_in=run.plan.tokens_in,
        tokens_out=run.plan.tokens_out,
    )

    run.lanes = fanout(
        run.plan,
        lanes,
        contexts=session.context_for(run.plan.workspaces()),
        inject_failure=inject_failure,
        observe=observe,
    )
    emit(
        observe,
        "merge_start",
        lanes=len(run.lanes.with_data()),
        wall_ms=run.lanes.wall_ms,
        slowest_ms=run.lanes.slowest_ms(),
    )
    run.merged = merge(
        question,
        run.lanes.answers,
        client=client,
        model=model,
        combine_on=run.plan.combine_on,
    )
    emit(
        observe,
        "checks",
        combinable=run.merged.combinable,
        results=[
            {"check": r.check, "verdict": r.verdict.value, "reason": r.reason}
            for r in run.merged.checks.results
        ],
    )

    session.remember(
        Turn(
            question=question,
            workspaces=run.plan.workspaces(),
            reply=run.merged.text,
            answers=run.lanes.answers,
            combinable=run.merged.combinable,
        ),
        contexts=_contexts(run.lanes, session.contexts),
    )
    run.total_ms = int((time.monotonic() - started) * 1000)
    emit(observe, "done", payload=run.payload())
    return run


def respond(
    lanes: Mapping[str, Lane],
    session: Session,
    workspace: str,
    reply: str,
    *,
    client: Any | None = None,
    model: str | None = None,
    observe: Observer | None = None,
) -> Run:
    """Answer a lane that asked a question, and re-merge with what the others already said.

    A workspace agent can stop mid-task and ask — "I found the spend metric but it has no
    campaign field; shall I use these instead?" A fan-out with nobody watching auto-confirms,
    which is a guess. When there *is* somebody watching, this is the path: their words go to
    that one workspace, on that workspace's own `contextId`, and the agent resumes where it
    stopped.

    Only the asking lane is called. The others already answered and re-asking them would
    cost the full fan-out to change nothing — and, worse, might return different numbers,
    making the merge a comparison across two different moments.

    The lane's *original* sub-question is restored onto the answer afterwards. The reply
    ("yes, use the campaign name") is not a question and would read as nonsense in an
    attribution line, while the merge needs to know what was actually being asked.
    """
    if not session.turns:
        raise ValueError("nothing to respond to: the session has no turns")
    if workspace not in lanes:
        raise ValueError(f"no lane configured for {workspace!r}")

    last = session.turns[-1]
    asked = next(
        (a.question for a in last.answers if a.workspace == workspace),
        last.question,
    )

    started = time.monotonic()
    emit(observe, "lane_start", workspace=workspace, question=reply)
    fresh = lanes[workspace].ask(reply, context_id=session.contexts.get(workspace))
    fresh = replace(fresh, question=asked)
    emit(
        observe,
        "lane_done",
        workspace=workspace,
        ok=fresh.ok(),
        returned_data=fresh.shape.returned_data,
        input_required=fresh.input_required,
        latency_ms=fresh.latency_ms,
        round_trips=fresh.round_trips,
        grain=fresh.shape.grain,
        error=fresh.error,
    )

    combined = session.union_for((fresh,))
    run = Run(question=last.question, enriched=(workspace,))
    run.lanes = FanoutReport(answers=combined, wall_ms=fresh.latency_ms)
    run.plan = Plan(
        question=last.question,
        steps=tuple(Step(workspace=a.workspace, question=a.question) for a in combined),
    )
    emit(observe, "merge_start", lanes=len(run.lanes.with_data()), wall_ms=fresh.latency_ms)
    run.merged = merge(last.question, combined, client=client, model=model)

    session.remember(
        Turn(
            question=last.question,
            workspaces=tuple(a.workspace for a in combined),
            reply=run.merged.text,
            answers=combined,
            combinable=run.merged.combinable,
        ),
        contexts=_contexts(run.lanes, session.contexts),
    )
    run.total_ms = int((time.monotonic() - started) * 1000)
    emit(observe, "done", payload=run.payload())
    return run


def enrich(
    registry: Registry,
    lanes: Mapping[str, Lane],
    session: Session,
    *,
    only: tuple[str, ...] | None = None,
    client: Any | None = None,
    model: str | None = None,
    observe: Observer | None = None,
) -> Run:
    """Re-ask the lanes whose part of the last answer is missing, and merge over the union.

    Reuses the *previous* plan's sub-questions rather than planning again: the question has
    not changed, only the lane's luck. Planning again would risk a differently worded
    sub-question, which would make the retry a different query and the comparison with the
    kept answers invalid.
    """
    if not session.turns:
        raise ValueError("nothing to enrich: the session has no turns")

    last = session.turns[-1]
    targets = tuple(only) if only else session.enrichable()
    if not targets:
        run = Run(question=last.question)
        run.merged = Merged(text=last.reply, answers=last.answers)
        return run

    # The sub-questions are recovered from the answers, which is why `Answer` carries the
    # question it was asked. Storing the plan separately would be a second source of truth
    # for the same thing.
    steps = tuple(
        Step(workspace=answer.workspace, question=answer.question)
        for answer in last.answers
        if answer.question
    )
    previous_plan = Plan(question=last.question, steps=steps)

    started = time.monotonic()
    run = Run(question=last.question, plan=previous_plan, enriched=targets)
    run.lanes = fanout(
        previous_plan,
        lanes,
        contexts=session.context_for(targets),
        only=frozenset(targets),
        observe=observe,
    )

    combined = session.union_for(run.lanes.answers)
    emit(observe, "merge_start", lanes=len(run.lanes.with_data()), wall_ms=run.lanes.wall_ms)
    run.merged = merge(last.question, combined, client=client, model=model)
    emit(
        observe,
        "checks",
        combinable=run.merged.combinable,
        results=[
            {"check": r.check, "verdict": r.verdict.value, "reason": r.reason}
            for r in run.merged.checks.results
        ],
    )

    session.remember(
        Turn(
            question=last.question,
            workspaces=tuple(answer.workspace for answer in combined),
            reply=run.merged.text,
            answers=combined,
            combinable=run.merged.combinable,
        ),
        contexts=_contexts(run.lanes, session.contexts),
    )
    run.total_ms = int((time.monotonic() - started) * 1000)
    emit(observe, "done", payload=run.payload())
    return run
