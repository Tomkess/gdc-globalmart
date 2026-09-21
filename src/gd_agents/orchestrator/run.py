"""One question in, one attributed answer out. The whole orchestrator, in two functions.

`ask` is a single turn: plan, fan out, check, merge. `enrich` is the retry path — re-ask only
the lanes whose part is still missing, and merge the fresh answers against the ones already
held. Given a lane fails on roughly half of multi-lane runs, that second function is not an
edge case.

Everything above this is the front end's business. Everything below is the protocol's. This
module is what FEAT-014 will call unchanged over MCP, which is why it takes lanes as an
argument rather than building them: a comparison whose orchestrator differs between the arms
measures the orchestrator.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from gd_agents.lane import Lane
from gd_agents.orchestrator.fanout import FanoutReport, fanout
from gd_agents.orchestrator.merge import Merged, merge
from gd_agents.orchestrator.plan import Plan, Step, plan
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


def ask(
    question: str,
    registry: Registry,
    lanes: Mapping[str, Lane],
    *,
    session: Session | None = None,
    client: Any | None = None,
    model: str | None = None,
    inject_failure: str | None = None,
) -> Run:
    """One turn: plan, fan out, check, merge.

    The route is recomputed every turn. A follow-up like "and did any of that show up in
    customer satisfaction?" needs a workspace the previous turn never touched, so reusing the
    earlier selection would answer the wrong question from the wrong place.
    """
    started = time.monotonic()
    session = session if session is not None else Session()
    run = Run(question=question)

    run.plan = plan(question, registry, client=client, model=model)
    run.lanes = fanout(
        run.plan,
        lanes,
        contexts=session.context_for(run.plan.workspaces()),
        inject_failure=inject_failure,
    )
    run.merged = merge(
        question,
        run.lanes.answers,
        client=client,
        model=model,
        combine_on=run.plan.combine_on,
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
    return run


def enrich(
    registry: Registry,
    lanes: Mapping[str, Lane],
    session: Session,
    *,
    only: tuple[str, ...] | None = None,
    client: Any | None = None,
    model: str | None = None,
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
    )

    combined = session.union_for(run.lanes.answers)
    run.merged = merge(last.question, combined, client=client, model=model)

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
    return run
