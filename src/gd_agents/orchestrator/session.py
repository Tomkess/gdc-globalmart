"""What a conversation remembers, and what it deliberately forgets.

One question is a plan, a fan-out and a merge. A *conversation* is several of those, and it
holds two things between turns:

**A `context_id` per engaged lane.** Each workspace runs its own A2A conversation, so a
follow-up must resume the right one. They are per lane and never shared: a workspace engaged
for the first time on turn three has no earlier turns to resume, and handing it another
workspace's context would be worse than handing it none.

**Each lane's last answer.** So a failed lane can be retried alone and the answer
re-synthesised over the union, rather than re-running lanes that already succeeded. A retry
of a four-lane question that re-asks all four costs four times what it needs to — and given
a lane fails on roughly half of multi-lane runs, that path gets used.

**What it does not remember: the route.** Every turn plans again. "And did any of that show
up in customer satisfaction?" needs a workspace the first turn never touched, so reusing the
previous selection would answer the wrong question from the wrong place. Re-planning costs
one call and is the difference between a conversation and a transcript.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gd_agents.lane import Answer


@dataclass
class Turn:
    """One exchange, kept so the next turn can build on it rather than restart."""

    question: str
    workspaces: tuple[str, ...]
    reply: str
    answers: tuple[Answer, ...] = ()
    combinable: bool = True

    def failed(self) -> tuple[str, ...]:
        return tuple(a.workspace for a in self.answers if not a.ok())

    def incomplete(self) -> tuple[str, ...]:
        """Lanes that contributed nothing — failed, or answered with no data.

        Both are candidates for enrichment, and the distinction matters to the reader but
        not to the retry: either way that workspace's part of the answer is missing.
        """
        return tuple(a.workspace for a in self.answers if not a.ok() or not a.shape.returned_data)


@dataclass
class Session:
    """One conversation across several turns."""

    contexts: dict[str, str] = field(default_factory=dict)
    """workspace -> A2A contextId, for the lanes engaged so far."""

    answers: dict[str, Answer] = field(default_factory=dict)
    """workspace -> its most recent answer, for the enrich path."""

    turns: list[Turn] = field(default_factory=list)

    def remember(self, turn: Turn, contexts: dict[str, str] | None = None) -> None:
        """Fold one turn into the conversation.

        A lane that failed does not overwrite an earlier good answer: the point of keeping
        answers is to hold on to what worked, and a retry that fails should leave the
        conversation no worse than before it.
        """
        self.turns.append(turn)
        for answer in turn.answers:
            contributed = answer.ok() and answer.shape.returned_data
            unseen = answer.workspace not in self.answers
            # Keep a good answer, or record a bad one where there was nothing. Never let a
            # failed retry overwrite something that worked.
            if contributed or unseen:
                self.answers[answer.workspace] = answer
        if contexts:
            self.contexts.update({k: v for k, v in contexts.items() if v})

    def context_for(self, workspaces: tuple[str, ...]) -> dict[str, str]:
        """Only the contexts of lanes that have actually been engaged.

        A workspace with no entry is asked cold, which is correct — it has no prior turn in
        that workspace to resume.
        """
        return {w: self.contexts[w] for w in workspaces if w in self.contexts}

    def prior(self) -> tuple[Any, ...]:
        """The conversation so far, in the shape the router needs.

        The route is still recomputed every turn — this is what the new plan is *about*, not
        a plan to copy. Without it a follow-up cannot be routed at all: "which of them
        converted best?" has no antecedent, and the router correctly and uselessly returns
        nothing.
        """
        from gd_agents.orchestrator.plan import Prior

        return tuple(
            Prior(question=turn.question, workspaces=turn.workspaces, reply=turn.reply)
            for turn in self.turns
        )

    def held(self) -> tuple[Answer, ...]:
        """Every lane answer the conversation still holds, for a turn that needs no new data."""
        return tuple(a for a in self.answers.values() if a.ok() and a.shape.returned_data)

    def enrichable(self) -> tuple[str, ...]:
        """Workspaces whose part of the last answer is still missing."""
        return self.turns[-1].incomplete() if self.turns else ()

    def union_for(self, fresh: tuple[Answer, ...]) -> tuple[Answer, ...]:
        """Fresh answers, plus the remembered ones for lanes not re-asked.

        This is what makes enrichment cheap: a retry of one lane is merged against what the
        other lanes already returned, so the reply improves without the cost of asking them
        again.
        """
        retried = {answer.workspace for answer in fresh}
        kept = [
            answer
            for workspace, answer in self.answers.items()
            if workspace not in retried and answer.ok() and answer.shape.returned_data
        ]
        return tuple(list(fresh) + kept)

    def summary_lines(self) -> list[str]:
        lines = [
            f"turns             : {len(self.turns)}",
            f"engaged lanes     : {', '.join(sorted(self.contexts)) or 'none'}",
            f"answers held      : {', '.join(sorted(self.answers)) or 'none'}",
        ]
        if self.turns:
            missing = self.enrichable()
            lines.append(f"enrichable        : {', '.join(missing) or 'nothing missing'}")
        return lines
