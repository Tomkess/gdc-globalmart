"""One answer from several, or several answers with a reason — never an invented link.

The merge is the second and last model call. It receives each lane's answer *and its shape*,
plus the verdicts of the deterministic checks, and writes the reply the user sees.

**What it is allowed to do:** compare, rank, sequence, narrate, attribute.

**What it may not do: compute.** Every number in its output must appear in some lane's
result. That is enforced after the fact by `check_provenance` rather than requested in the
prompt, because a prompt cannot be held to anything. If the merge invents a value the reply
is rejected and the lanes are reported separately instead — a worse-reading answer that is
true, over a better-reading one that is not.

**When the checks refuse, refusing is the answer.** Two answers with no common key are
presented side by side with the reason. The ticket forbids side-by-side as the *default*,
but an honest "these do not combine, here is each" beats a fabricated connection —
particularly for a customer whose own aggregate workspace already failed them.

**Attribution is structural.** Each lane's answer is kept verbatim and addressable whatever
the merge says about it, so provenance survives a model that decided to paraphrase.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from gd_agents.lane import Answer
from gd_agents.orchestrator.checks import (
    CheckReport,
    Provenance,
    check_provenance,
    model_check_prompt,
    run_checks,
)
from gd_agents.orchestrator.plan import DEFAULT_MODEL, MODEL_ENV, PlanError, make_client

MAX_TOKENS = 2000

SYSTEM_PROMPT = """\
You write one answer from several, each computed in a different GoodData workspace against a
different data model.

Absolute rule: **you may not compute.** Compare, rank, sequence and narrate as much as you
like, but every number you write must appear verbatim in one of the answers you were given.
Never add, subtract, divide or average across workspaces. A ratio spanning two workspaces —
spend from one divided by a score from another — is meaningless however reasonable it sounds,
because the two were measured over different grains and different populations. If you want to
express a relationship, describe it in words.

Say which workspace each part came from. Name it.

You are given the verdicts of automatic checks. If any of them failed, do not assert a
connection: report each workspace's answer separately and state the reason in one sentence.

Also judge these yourself, and say so if either is a problem:
{model_checks}

A lane that failed, or answered without data, has not contributed. Say plainly what is
missing rather than implying it.

Reply as prose for a reader. No JSON, no headings, no preamble about what you are doing.
"""


@dataclass
class Merged:
    text: str = ""
    combinable: bool = True
    checks: CheckReport = field(default_factory=CheckReport)
    provenance: Provenance = field(default_factory=Provenance)
    answers: tuple[Answer, ...] = ()
    tokens_in: int = 0
    tokens_out: int = 0
    rejected: str | None = None
    """Set when the merge was thrown away — the reply then holds the separate answers."""

    def ok(self) -> bool:
        return bool(self.text) and self.rejected is None

    def summary_lines(self) -> list[str]:
        lines = [
            f"combinable        : {self.combinable}",
            f"provenance        : {'ok' if self.provenance.ok() else 'INVENTED'}"
            f" ({self.provenance.checked} number(s) checked against {self.provenance.known} known)",
            f"merge tokens      : {self.tokens_in:,} in / {self.tokens_out:,} out",
        ]
        if self.rejected:
            lines.append(f"REJECTED          : {self.rejected}")
        lines.extend(self.checks.summary_lines())
        return lines


def lane_block(answer: Answer) -> str:
    """One lane's contribution, with its shape, as the merge prompt sees it."""
    shape = answer.shape
    facts = [
        f"asked: {answer.question}",
        f"grain: {shape.grain or 'not reported'}",
        f"period: {shape.time_from or '?'} .. {shape.time_to or '?'}",
        f"filters: {', '.join(shape.filters) or 'none reported'}",
        f"units: {shape.units or 'not reported'}",
        f"returned data: {'yes' if shape.returned_data else 'no'}",
    ]
    if answer.error:
        facts.append(f"FAILED: {answer.error}")
    body = answer.text or "(no answer)"
    numbers = ", ".join(answer.numbers[:40]) or "none"
    return (
        f"### workspace: {answer.workspace}\n"
        + "\n".join(f"- {fact}" for fact in facts)
        + f"\n\nanswer:\n{body}\n\nvalues it returned: {numbers}\n"
    )


def user_prompt(question: str, answers: Sequence[Answer], checks: CheckReport) -> str:
    verdicts = "\n".join(f"- {r.check}: {r.verdict.value} — {r.reason}" for r in checks.results)
    blocks = "\n".join(lane_block(answer) for answer in answers)
    return (
        f"User question: {question}\n\n"
        f"Automatic check verdicts:\n{verdicts or '- none run'}\n\n"
        f"Workspace answers:\n\n{blocks}"
    )


def separate_answers(question: str, answers: Sequence[Answer], checks: CheckReport) -> str:
    """The fallback reply: each lane's answer, attributed, with the reason they do not combine.

    Deterministic and model-free on purpose. It is used when the checks refuse *and* when a
    merge is rejected for inventing a number, and in the second case reaching for the model
    again would be asking the thing that just failed to try harder.
    """
    reason = checks.reasons() or "these answers do not share a dimension that would let them be combined"
    parts = [f"These results could not be combined: {reason}", ""]
    for answer in answers:
        parts.append(f"**{answer.workspace}** — asked: {answer.question}")
        if not answer.ok():
            parts.append(f"  did not answer: {answer.error}")
        elif not answer.shape.returned_data:
            parts.append("  answered, but returned no data for this question.")
        else:
            parts.append(f"  {answer.text.strip()}")
        parts.append("")
    return "\n".join(parts).strip()


def merge(
    question: str,
    answers: Sequence[Answer],
    *,
    client: Any | None = None,
    model: str | None = None,
    combine_on: str | None = None,
) -> Merged:
    """Write the reply. Runs the checks first, and the provenance check after.

    `combine_on` is what the plan expected to join on. Passed through as context for the
    model rather than as permission: the checks decide, and the plan was written before any
    answer came back.
    """
    import os

    usable = [answer for answer in answers if answer.ok() and answer.shape.returned_data]
    checks = run_checks(list(answers))
    result = Merged(answers=tuple(answers), checks=checks, combinable=checks.combinable())

    if not usable:
        result.text = separate_answers(question, answers, checks)
        result.combinable = False
        return result

    if not checks.combinable():
        # Refusing is the answer. Reaching for the model here would invite it to argue
        # around a verdict the code already reached.
        result.text = separate_answers(question, answers, checks)
        return result

    if client is None:
        client, resolved = make_client()
        model = model or resolved
    model = model or os.environ.get(MODEL_ENV, DEFAULT_MODEL)

    context = user_prompt(question, answers, checks)
    if combine_on:
        context += f"\n\nThe plan expected these to combine on: {combine_on}"

    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT.format(model_checks=model_check_prompt()),
        messages=[{"role": "user", "content": context}],
    )
    text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
    usage = getattr(response, "usage", None)
    result.tokens_in = int(getattr(usage, "input_tokens", 0) or 0)
    result.tokens_out = int(getattr(usage, "output_tokens", 0) or 0)

    result.provenance = check_provenance(text, list(answers))
    if not result.provenance.ok():
        # The merge computed something. Rejecting it and falling back is the whole point of
        # checking after the fact: a worse-reading answer that is true beats a better-reading
        # one that is not.
        result.rejected = result.provenance.as_result().reason
        result.text = separate_answers(question, answers, checks)
        result.combinable = False
        return result

    result.text = text
    return result


def merge_or_raise(question: str, answers: Sequence[Answer], **kwargs: Any) -> Merged:
    """`merge`, but a missing model client is an error rather than a silent fallback."""
    if not answers:
        raise PlanError("nothing to merge: no lane returned")
    return merge(question, answers, **kwargs)
