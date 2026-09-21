# The orchestrator's foundations: the Lane contract, the registry, and the profiler.
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from gd_agents.lane import Answer, Lane, Shape
from gd_agents.profile import Probe, _base_first, _titles, describe, discovery_findings
from gd_agents.registry import Registry, RegistryError, WorkspaceEntry

# --- the Lane contract --------------------------------------------------------


def test_a_minimal_implementation_satisfies_the_lane_protocol() -> None:
    """Two methods, deliberately. Anything richer leaks a protocol's shape upward and
    quietly makes the A2A/MCP comparison unfair."""

    class Stub:
        workspace = "w"

        def describe(self) -> str:
            return "d"

        def ask(self, question: str, *, context_id: str | None = None) -> Answer:
            return Answer(workspace="w", question=question, text="x")

    assert isinstance(Stub(), Lane)


def test_an_answer_carrying_an_error_is_not_ok() -> None:
    """A failed lane degrades the reply; it never ends the query, so it comes back as an
    Answer rather than an exception."""
    assert not Answer(workspace="w", question="q", text="", error="timeout").ok()
    assert Answer(workspace="w", question="q", text="hi").ok()


def test_returning_no_data_is_distinct_from_failing() -> None:
    """A lane that answered and found nothing must not read as a lane that broke."""
    empty = Answer(workspace="w", question="q", text="no rows", shape=Shape(returned_data=False))
    assert empty.ok()
    assert not empty.shape.returned_data


# --- the registry -------------------------------------------------------------


def registry() -> Registry:
    return Registry(
        host="https://example.invalid",
        token_env="TOKEN",
        entries=(
            WorkspaceEntry(id="a", title="A", description="Measures spend"),
            WorkspaceEntry(id="b", title="B", description="Measures sentiment"),
        ),
    )


def test_the_prompt_block_is_one_line_per_workspace() -> None:
    lines = registry().prompt_block().splitlines()
    assert len(lines) == 2
    assert all(line.startswith("- ") for line in lines)
    assert "Measures spend" in lines[0]


def test_an_unknown_workspace_is_refused() -> None:
    with pytest.raises(RegistryError):
        registry().require("nope")


def test_a_workspace_without_a_description_is_refused(tmp_path: Path) -> None:
    """A workspace nothing can be said about cannot be routed to, so it is an error at load
    rather than a silent hole in the routing prompt."""
    path = tmp_path / "agents.yaml"
    path.write_text(
        "host: https://example.invalid\ntoken_env: TOKEN\nworkspaces:\n  - id: a\n    title: A\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryError, match="description"):
        Registry.load(path)


def test_a_registry_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "agents.yaml"
    registry().write(path)
    assert Registry.load(path) == registry()


# --- the profiler -------------------------------------------------------------


def test_repeated_titles_collapse() -> None:
    """Knowledge is chunked per section, so several memory items share one document title.
    Listing it four times costs tokens and says nothing."""
    rows = [{"attributes": {"title": "Dates"}} for _ in range(4)] + [{"attributes": {"title": "Metrics"}}]
    assert _titles(rows) == ("Dates", "Metrics")


def test_derived_metrics_sort_after_base_metrics() -> None:
    """A period comparison says nothing about subject matter that its base metric has not
    already said, so it must not crowd the base ones out of the sample."""
    ordered = _base_first(("MoM: Orders", "Total Orders", "YoY: Orders", "Average Order Value"))
    assert ordered[:2] == ("Total Orders", "Average Order Value")


def test_a_description_leads_with_what_the_workspace_measures() -> None:
    """Fact datasets distinguish workspaces; dimensions are conformed and therefore say the
    same thing about all of them."""
    probe = Probe(
        workspace="w",
        title="W",
        subjects=("Campaign Spend", "Email Send"),
        metrics=("Total Spend",),
        metric_count=1,
    )
    text = describe(probe)
    assert text.startswith("Measures Campaign Spend, Email Send")
    assert "Total Spend" in text


def test_identical_agent_cards_are_reported_as_a_finding() -> None:
    """The first gap-list item, derived from a real run rather than written from memory."""
    probes = [
        Probe(workspace=f"w{n}", agent_card_description="GoodData Analytics AI Agent") for n in range(4)
    ]
    findings = discovery_findings(probes)

    assert any("identical A2A agent card" in finding for finding in findings)


def test_findings_name_only_real_entity_kinds() -> None:
    """An earlier version derived the kind from the last path segment, which turned
    `/entities/workspaces/globalmart-customer` into a workspace id masquerading as an
    entity kind."""
    probe = Probe(workspace="globalmart-customer")
    probe.reached = [
        "/api/v1/entities/workspaces/globalmart-customer",
        "/api/v1/entities/workspaces/globalmart-customer/metrics",
    ]
    findings = discovery_findings([probe, Probe(workspace="other")])

    assert not any("globalmart-customer through the metadata API" in f for f in findings)
    assert any("metrics through the metadata API" in f for f in findings)


# --- the A2A lane -------------------------------------------------------------
#
# Fixtures below are the real shape of a Task, taken from a live agent on 2026-09-21. The
# ordering inside it is the whole point: the reply is in status.message, the values are in
# the visualization-data artifact, and history is the agent thinking aloud.


def completed_task() -> dict:
    return {
        "result": {
            "kind": "task",
            "contextId": "ctx-1",
            "status": {
                "state": "completed",
                "message": {
                    "role": "agent",
                    "parts": [
                        {
                            "kind": "text",
                            "text": (
                                "Created a line chart showing "
                                "{metric/metric_l1_total_campaign_spend} by month."
                            ),
                        }
                    ],
                },
            },
            "history": [
                {"role": "user", "parts": [{"kind": "text", "text": "Show spend by month."}]},
                {
                    "role": "agent",
                    "parts": [{"kind": "text", "text": "**Creating a chart**\n\nI need to focus on…"}],
                },
            ],
            "artifacts": [
                {"name": "visualization", "parts": [{"kind": "data", "data": {"type": "line"}}]},
                {
                    "name": "visualization-data",
                    "parts": [
                        {
                            "kind": "data",
                            "data": {
                                "formattedRows": [
                                    {"Month/Year": "2026-04", "Total Campaign Spend": "11,944.45"},
                                    {"Month/Year": "2026-05", "Total Campaign Spend": "9,726.62"},
                                ]
                            },
                        }
                    ],
                },
            ],
        }
    }


def test_the_answer_comes_from_status_not_history() -> None:
    """History is chain-of-thought. Reading it — the obvious first guess, and what the
    existing reference client does — presents reasoning as a result."""
    from gd_agents.a2a.client import answer_text

    text, source = answer_text(completed_task())

    assert source == "status.message"
    assert text.startswith("Created a line chart")
    assert "I need to focus on" not in text


def test_history_is_flagged_when_it_is_all_there_is() -> None:
    from gd_agents.a2a.client import answer_text

    task = completed_task()
    task["result"]["status"] = {"state": "completed"}
    task["result"]["artifacts"] = []
    _, source = answer_text(task)

    assert "reasoning" in source, "falling back to history must say what it is"


def test_provenance_comes_from_the_data_artifact() -> None:
    """The text narrates; the artifact carries the values. The no-computation rule needs the
    values, or it has nothing to hold a merged answer to."""
    from gd_agents.a2a.client import data_artifacts, numbers_from_artifacts

    numbers = numbers_from_artifacts(data_artifacts(completed_task()))

    assert "11,944.45" in numbers
    assert "9,726.62" in numbers
    assert not any(value.startswith("{") for value in numbers), (
        "a dict row was stringified whole, which matches nothing a merge would write"
    )


def test_digits_inside_identifiers_are_not_provenance() -> None:
    """`metric_l1_total_campaign_spend` must not contribute a "1"; a merge could then
    justify any number that happens to appear in a metric id."""
    from gd_agents.a2a.client import numbers_in

    assert numbers_in("showing {metric/metric_l1_total_campaign_spend} by month") == ()
    assert "6" in numbers_in("for the last 6 months")


def test_years_are_not_provenance() -> None:
    from gd_agents.a2a.client import numbers_in

    assert numbers_in("revenue in 2026 was 11,944.45") == ("11,944.45",)


def test_a_clarification_request_is_not_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """An agent asking which metric was meant has not answered. Treating the question as a
    result is how a merge ends up narrating a prompt back to the user."""
    from gd_agents.a2a.client import A2ALane
    from gd_agents.transport import Host

    task = completed_task()
    task["result"]["status"]["state"] = "input-required"
    task["result"]["artifacts"] = []

    lane = A2ALane(host=Host(url="https://example.invalid", token="t"), workspace="w")
    monkeypatch.setattr(type(lane.host), "post", lambda *a, **k: task)

    answer = lane.ask("total spend?")

    assert answer.ok(), "a clarification request is not a failure"
    assert not answer.shape.returned_data


def test_a_transport_failure_becomes_an_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    from gd_agents.a2a.client import A2ALane
    from gd_agents.transport import Host, TransportError

    def boom(*args: object, **kwargs: object) -> None:
        raise TransportError("timed out")

    lane = A2ALane(host=Host(url="https://example.invalid", token="t"), workspace="w")
    monkeypatch.setattr(type(lane.host), "post", boom)

    answer = lane.ask("anything")

    assert not answer.ok()
    assert "timed out" in (answer.error or "")


# --- plan: route and decompose ------------------------------------------------


def plan_registry() -> Registry:
    return Registry(
        host="https://example.invalid",
        token_env="TOKEN",
        entries=(
            WorkspaceEntry(id="mkt", title="Marketing", description="Measures Campaign Spend"),
            WorkspaceEntry(id="cust", title="Customers", description="Measures NPS Response"),
        ),
    )


def test_a_plan_carries_a_sub_question_per_workspace() -> None:
    """Decomposition is what makes this federation: neither workspace is asked the user's
    question, because neither can answer it."""
    from gd_agents.orchestrator.plan import parse_plan

    raw = (
        '{"workspaces": ['
        '{"id": "mkt", "question": "Show Total Campaign Spend by month", "why": "spend"},'
        '{"id": "cust", "question": "Show Average NPS by month", "why": "satisfaction"}],'
        ' "reasoning": "needs both", "combine_on": "month"}'
    )
    result = parse_plan("did spend move satisfaction?", raw, plan_registry())

    assert result.workspaces() == ("mkt", "cust")
    assert result.steps[0].question != "did spend move satisfaction?"
    assert result.combine_on == "month"


def test_a_hallucinated_workspace_is_dropped_and_noted() -> None:
    """Calling a workspace the caller cannot see is a routing error. Dropping it silently
    would hide it from the measurement, which is the point of measuring."""
    from gd_agents.orchestrator.plan import parse_plan

    raw = '{"workspaces": [{"id": "finance", "question": "x"}, {"id": "mkt", "question": "y"}]}'
    result = parse_plan("q", raw, plan_registry())

    assert result.workspaces() == ("mkt",)
    assert any("finance" in note for note in result.notes)


def test_a_plan_with_no_usable_workspace_is_an_error() -> None:
    from gd_agents.orchestrator.plan import PlanError, parse_plan

    with pytest.raises(PlanError):
        parse_plan("q", '{"workspaces": []}', plan_registry())


def test_not_combinable_is_distinct_from_unset() -> None:
    """ "These do not combine" is a finding the merge must act on, so it cannot be confused
    with the model having forgotten to say."""
    from gd_agents.orchestrator.plan import parse_plan

    raw = '{"workspaces": [{"id": "mkt", "question": "x"}], "combine_on": null}'
    assert parse_plan("q", raw, plan_registry()).combine_on is None


def test_code_fences_are_tolerated() -> None:
    """Models add fences even when told not to; re-prompting costs more than stripping."""
    from gd_agents.orchestrator.plan import parse_plan

    raw = '```json\n{"workspaces": [{"id": "mkt", "question": "x"}]}\n```'
    assert parse_plan("q", raw, plan_registry()).workspaces() == ("mkt",)


def test_a_non_json_reply_is_an_error_naming_what_came_back() -> None:
    from gd_agents.orchestrator.plan import PlanError, parse_plan

    with pytest.raises(PlanError, match="not JSON"):
        parse_plan("q", "I think you should ask marketing.", plan_registry())


# --- the script ---------------------------------------------------------------


def test_the_committed_script_loads_and_every_question_has_expectations() -> None:
    """A question with no `expect` measures nothing, so it must not be loadable."""
    from gd_agents.script import load_script

    questions, conversations = load_script(Path("config/questions.yaml"))

    assert len(questions) >= 9
    assert conversations
    assert all(question.expect for question in questions)
    assert all(turn.expect for conversation in conversations for turn in conversation.turns)


def test_a_question_without_expectations_is_refused(tmp_path: Path) -> None:
    from gd_agents.script import ScriptError, load_script

    path = tmp_path / "q.yaml"
    path.write_text("questions:\n  - id: x\n    question: hello?\n", encoding="utf-8")
    with pytest.raises(ScriptError, match="expect"):
        load_script(path)


def test_over_routing_and_under_routing_are_reported_separately() -> None:
    """They are different problems with different fixes: one wastes latency and tokens, the
    other returns an incomplete answer."""
    from gd_agents.script import Question, compare

    question = Question(id="x", question="q", expect=("a", "b"))

    assert compare(question, ("a", "b")).exact()
    assert compare(question, ("a",)).missed == ("b",)
    assert compare(question, ("a", "b", "c")).extra == ("c",)
    assert not compare(question, ("a", "b", "c")).exact()


def test_the_script_covers_the_cases_the_spec_requires() -> None:
    """The script is an acceptance criterion, so its coverage is asserted rather than
    assumed: single-workspace routing, federation, all-lanes latency, a merge refusal, the
    Overview beat, and degradation."""
    from gd_agents.script import load_script

    questions, _ = load_script(Path("config/questions.yaml"))
    kinds = {question.kind for question in questions}

    for required in ("routing", "federation", "latency", "merge-refusal", "overview-problem", "degradation"):
        assert required in kinds, f"the script has no {required} case"
    assert any(question.inject_failure for question in questions)
    assert any(len(question.expect) == 1 for question in questions)
    assert any(len(question.expect) == 4 for question in questions)


# --- fanout: parallel lanes, isolated failures --------------------------------


def fake_plan(*workspaces: str):  # type: ignore[no-untyped-def]
    from gd_agents.orchestrator.plan import Plan, Step

    return Plan(
        question="q",
        steps=tuple(Step(workspace=w, question=f"ask {w}") for w in workspaces),
    )


class SlowLane:
    """A lane that sleeps, so parallelism is observable rather than assumed."""

    def __init__(self, workspace: str, seconds: float, fail: bool = False) -> None:
        self.workspace = workspace
        self.seconds = seconds
        self.fail = fail

    def describe(self) -> str:
        return ""

    def ask(self, question: str, *, context_id: str | None = None) -> Answer:
        import time as _time

        _time.sleep(self.seconds)
        if self.fail:
            return Answer(workspace=self.workspace, question=question, text="", error="boom")
        return Answer(
            workspace=self.workspace, question=question, text="ok", latency_ms=int(self.seconds * 1000)
        )


def test_lanes_run_in_parallel_not_in_sequence() -> None:
    """The cost of a fan-out must be the slowest lane, not the sum. Sequential lanes turn a
    30-second answer into two minutes, which is the difference between a demo and a wait."""
    from gd_agents.orchestrator.fanout import fanout

    lanes = {"a": SlowLane("a", 0.3), "b": SlowLane("b", 0.3), "c": SlowLane("c", 0.3)}
    report = fanout(fake_plan("a", "b", "c"), lanes)

    assert len(report.answers) == 3
    assert report.wall_ms < 700, f"lanes did not overlap: {report.wall_ms}ms for 3x300ms"


def test_one_failing_lane_does_not_end_the_query() -> None:
    from gd_agents.orchestrator.fanout import fanout

    lanes = {"a": SlowLane("a", 0.01), "b": SlowLane("b", 0.01, fail=True)}
    report = fanout(fake_plan("a", "b"), lanes)

    assert len(report.ok()) == 1
    assert len(report.failed()) == 1
    assert report.failed()[0].workspace == "b"


def test_a_lane_that_raises_is_reported_not_propagated() -> None:
    """A lane must never raise upward. Failing a whole question because one agent threw is
    the behaviour a demo cannot survive."""
    from gd_agents.orchestrator.fanout import fanout

    class Exploding:
        workspace = "x"

        def describe(self) -> str:
            return ""

        def ask(self, question: str, *, context_id: str | None = None) -> Answer:
            raise RuntimeError("socket closed")

    report = fanout(fake_plan("x"), {"x": Exploding()})

    assert len(report.failed()) == 1
    assert "socket closed" in (report.failed()[0].error or "")


def test_answers_come_back_in_plan_order_not_completion_order() -> None:
    """The report should read the way the plan was written, or a fast lane appears to have
    been chosen first."""
    from gd_agents.orchestrator.fanout import fanout

    lanes = {"slow": SlowLane("slow", 0.25), "fast": SlowLane("fast", 0.01)}
    report = fanout(fake_plan("slow", "fast"), lanes)

    assert [a.workspace for a in report.answers] == ["slow", "fast"]


def test_only_restricts_execution_for_the_enrich_path() -> None:
    """Retrying a failed lane must not re-run the lanes that already succeeded."""
    from gd_agents.orchestrator.fanout import fanout

    lanes = {"a": SlowLane("a", 0.01), "b": SlowLane("b", 0.01)}
    report = fanout(fake_plan("a", "b"), lanes, only=frozenset({"b"}))

    assert [a.workspace for a in report.answers] == ["b"]


def test_an_injected_failure_needs_no_outage() -> None:
    """The script's degradation case has to be demonstrable on demand."""
    from gd_agents.orchestrator.fanout import fanout

    lanes = {"a": SlowLane("a", 0.01), "b": SlowLane("b", 0.01)}
    report = fanout(fake_plan("a", "b"), lanes, inject_failure="b")

    assert len(report.failed()) == 1
    assert "injected" in (report.failed()[0].error or "")


def test_a_missing_lane_is_noted_rather_than_crashing() -> None:
    from gd_agents.orchestrator.fanout import fanout

    report = fanout(fake_plan("a", "ghost"), {"a": SlowLane("a", 0.01)})

    assert [a.workspace for a in report.answers] == ["a"]
    assert any("ghost" in note for note in report.notes)


def test_a_clarification_request_is_answered_but_holds_no_data() -> None:
    """`with_data` is what the merge should synthesise from. A lane that asked a question
    back is neither a failure nor a result."""
    from gd_agents.orchestrator.fanout import FanoutReport

    report = FanoutReport(
        answers=(
            Answer(workspace="a", question="q", text="here it is"),
            Answer(workspace="b", question="q", text="which metric?", shape=Shape(returned_data=False)),
        )
    )

    assert len(report.ok()) == 2
    assert [a.workspace for a in report.with_data()] == ["a"]


# --- transient retry ----------------------------------------------------------


def test_a_transient_server_error_is_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Observed live: a lane returned 502 while an identical request seconds later worked.
    Losing a workspace because the gateway hiccuped is noise, not a finding."""
    from gd_agents.a2a.client import A2ALane
    from gd_agents.transport import Host, TransportError

    calls: list[int] = []

    def flaky(self: object, path: str, body: object, **kwargs: object) -> dict:
        calls.append(1)
        if len(calls) == 1:
            raise TransportError("POST /x -> HTTP 502: Bad Gateway")
        return completed_task()

    lane = A2ALane(host=Host(url="https://example.invalid", token="t"), workspace="w")
    monkeypatch.setattr(type(lane.host), "post", flaky)

    answer = lane.ask("q")

    assert answer.ok()
    assert len(calls) == 2
    assert answer.round_trips == 2, "the retry must stay visible in the cost"


def test_a_client_error_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 4xx is the server saying the request was wrong. Asking again will not fix it."""
    from gd_agents.a2a.client import A2ALane
    from gd_agents.transport import Host, TransportError

    calls: list[int] = []

    def refuse(self: object, path: str, body: object, **kwargs: object) -> dict:
        calls.append(1)
        raise TransportError("POST /x -> HTTP 400: Bad Request")

    lane = A2ALane(host=Host(url="https://example.invalid", token="t"), workspace="w")
    monkeypatch.setattr(type(lane.host), "post", refuse)

    answer = lane.ask("q")

    assert not answer.ok()
    assert len(calls) == 1


# --- merge checks -------------------------------------------------------------


def shaped(
    workspace: str,
    *,
    grain: str = "month",
    units: str = "USD",
    numbers: tuple[str, ...] = ("1",),
    frm: str = "2026-04-01",
    to: str = "2026-09-30",
    data: bool = True,
    filters: tuple[str, ...] = (),
    error: str | None = None,
) -> Answer:
    return Answer(
        workspace=workspace,
        question="q",
        text="t",
        numbers=numbers,
        error=error,
        shape=Shape(grain=grain, units=units, time_from=frm, time_to=to, returned_data=data, filters=filters),
    )


def test_the_registry_declares_who_decides_each_check() -> None:
    """Adding a ninth check must be a data entry, so the registry has to carry everything a
    caller needs rather than the knowledge living in the merge code."""
    from gd_agents.orchestrator.checks import CHECKS, Decider

    assert len(CHECKS) == 8
    assert {c.id for c in CHECKS if c.decided_by is Decider.MODEL} == {
        "metric_identity",
        "population_parity",
    }
    assert all(c.guards_against for c in CHECKS), "a check that cannot say what it guards"
    assert all(
        c.run is not None for c in CHECKS if c.decided_by is Decider.CODE and c.id != "numeric_provenance"
    )


def test_agreeing_lanes_are_combinable() -> None:
    """Two lanes reporting the same grain is the strongest pass. An earlier version counted
    distinct values, which made agreement indistinguishable from silence."""
    from gd_agents.orchestrator.checks import Verdict, run_checks

    report = run_checks([shaped("a"), shaped("b")])

    assert report.combinable()
    by_id = {r.check: r for r in report.results}
    assert by_id["shared_dimension"].verdict is Verdict.PASS
    assert by_id["unit_compatibility"].verdict is Verdict.PASS


def test_different_grains_block_the_merge() -> None:
    from gd_agents.orchestrator.checks import run_checks

    report = run_checks([shaped("a", grain="month"), shaped("b", grain="store")])

    assert not report.combinable()
    assert "no common key" in report.reasons()


def test_different_time_windows_block_the_merge() -> None:
    from gd_agents.orchestrator.checks import run_checks

    report = run_checks([shaped("a", to="2026-09-30"), shaped("b", to="2026-06-30")])

    assert not report.combinable()
    assert "no shared period" in report.reasons()


def test_mixed_units_block_the_merge() -> None:
    from gd_agents.orchestrator.checks import run_checks

    assert not run_checks([shaped("a", units="USD"), shaped("b", units="EUR")]).combinable()


def test_a_failed_lane_blocks_combination_and_says_what_to_do() -> None:
    from gd_agents.orchestrator.checks import run_checks

    report = run_checks([shaped("a"), shaped("b", error="boom")])

    assert not report.combinable()
    assert "Synthesise only from what answered" in report.reasons()


def test_unknown_is_not_pass() -> None:
    """A check cannot pass on an absence it never established, or a lane that reported
    nothing would silently license any combination."""
    from gd_agents.orchestrator.checks import Verdict, run_checks

    report = run_checks([shaped("a", grain=""), shaped("b", grain="")])
    by_id = {r.check: r for r in report.results}

    assert by_id["shared_dimension"].verdict is Verdict.UNKNOWN
    assert by_id["shared_dimension"].verdict is not Verdict.PASS


def test_a_single_lane_has_nothing_to_combine() -> None:
    from gd_agents.orchestrator.checks import run_checks

    assert run_checks([shaped("a")]).combinable()


# --- numeric provenance: the hard rule ----------------------------------------


def test_an_answer_quoting_lane_numbers_passes() -> None:
    from gd_agents.orchestrator.checks import check_provenance

    lanes = [shaped("a", numbers=("11,944.45",)), shaped("b", numbers=("27.04",))]

    assert check_provenance("Spend was 11,944.45 while NPS sat at 27.04.", lanes).ok()


def test_a_ratio_across_workspaces_is_caught() -> None:
    """ "Cost per NPS point" is the archetype: both inputs real, the quotient meaningless
    because the grains and populations differ. No prompt can be trusted to refuse it."""
    from gd_agents.orchestrator.checks import check_provenance

    lanes = [shaped("a", numbers=("11944.45",)), shaped("b", numbers=("27.04",))]
    result = check_provenance("Cost per NPS point was 441.73.", lanes)

    assert not result.ok()
    assert "441.73" in result.invented
    assert "never compute" in result.as_result().reason


def test_separators_do_not_count_as_invention() -> None:
    """11,944.45 and 11944.45 are one number written two ways."""
    from gd_agents.orchestrator.checks import check_provenance

    assert check_provenance("Spend was 11944.45.", [shaped("a", numbers=("11,944.45",))]).ok()


def test_years_are_not_treated_as_provenance() -> None:
    """Counting them would licence any value between 1900 and 2200."""
    from gd_agents.orchestrator.checks import check_provenance

    assert check_provenance("In 2026 spend was 11,944.45.", [shaped("a", numbers=("11,944.45",))]).ok()


def test_the_model_checks_are_posed_not_assumed() -> None:
    """Judgement checks must reach the merge prompt explicitly, or they are just hope."""
    from gd_agents.orchestrator.checks import model_check_prompt

    prompt = model_check_prompt()

    assert "metric_identity" in prompt
    assert "population_parity" in prompt


# --- merge --------------------------------------------------------------------


class FakeMessages:
    """Replies in order, repeating the last one. A whole turn is two model calls — the plan
    and the merge — so a single canned reply cannot stand in for both."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies) or [""]
        self.calls = 0

    def create(self, **kwargs: object):  # type: ignore[no-untyped-def]
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        block = type("B", (), {"type": "text", "text": reply})()
        usage = type("U", (), {"input_tokens": 10, "output_tokens": 20})()
        return type("R", (), {"content": [block], "usage": usage})()


class FakeClient:
    def __init__(self, *replies: str) -> None:
        self.messages = FakeMessages(*replies)


def test_a_clean_merge_is_returned_verbatim() -> None:
    from gd_agents.orchestrator.merge import merge

    lanes = [shaped("mkt", numbers=("11,944.45",)), shaped("cust", numbers=("27.04",))]
    client = FakeClient("Spend of 11,944.45 in marketing sat alongside an NPS of 27.04 in customer.")

    result = merge("q", lanes, client=client, model="m")

    assert result.ok()
    assert result.combinable
    assert "11,944.45" in result.text
    assert client.messages.calls == 1


def test_a_merge_that_computes_is_rejected_and_replaced() -> None:
    """The whole reason provenance is checked after the fact: a prompt cannot be held to
    anything, so the output is verified and thrown away if it invented a number."""
    from gd_agents.orchestrator.merge import merge

    lanes = [shaped("mkt", numbers=("11944.45",)), shaped("cust", numbers=("27.04",))]
    client = FakeClient("Cost per NPS point was 441.73, which is efficient.")

    result = merge("q", lanes, client=client, model="m")

    assert not result.ok()
    assert result.rejected and "never compute" in result.rejected
    assert "441.73" not in result.text
    assert "could not be combined" in result.text


def test_a_blocked_check_skips_the_model_entirely() -> None:
    """Refusing is the answer. Calling the model here would invite it to argue around a
    verdict the code already reached."""
    from gd_agents.orchestrator.merge import merge

    lanes = [shaped("mkt", grain="month"), shaped("cust", grain="store")]
    client = FakeClient("they are clearly related")

    result = merge("q", lanes, client=client, model="m")

    assert client.messages.calls == 0
    assert not result.combinable
    assert "no common key" in result.text


def test_a_failed_lane_is_named_not_implied() -> None:
    from gd_agents.orchestrator.merge import merge

    lanes = [shaped("mkt"), shaped("cust", error="agent reported failed")]
    result = merge("q", lanes, client=FakeClient("x"), model="m")

    assert "cust" in result.text
    assert "did not answer" in result.text


def test_a_lane_that_returned_no_data_says_so() -> None:
    from gd_agents.orchestrator.merge import merge

    lanes = [shaped("mkt"), shaped("cust", data=False)]
    result = merge("q", lanes, client=FakeClient("x"), model="m")

    assert "returned no data" in result.text


def test_with_nothing_usable_the_reply_is_still_honest() -> None:
    from gd_agents.orchestrator.merge import merge

    lanes = [shaped("mkt", error="boom"), shaped("cust", error="boom")]
    result = merge("q", lanes, client=FakeClient("x"), model="m")

    assert not result.combinable
    assert result.text.count("did not answer") == 2


def test_the_prompt_carries_each_lane_shape_and_its_values() -> None:
    """The checks need shape; provenance needs the values. A prompt without them asks the
    model to judge combinability on prose alone."""
    from gd_agents.orchestrator.checks import run_checks
    from gd_agents.orchestrator.merge import user_prompt

    lanes = [shaped("mkt", numbers=("11,944.45",))]
    text = user_prompt("q", lanes, run_checks(lanes))

    assert "grain: month" in text
    assert "11,944.45" in text
    assert "returned data: yes" in text


def test_the_system_prompt_poses_the_judgement_checks() -> None:
    from gd_agents.orchestrator.checks import model_check_prompt
    from gd_agents.orchestrator.merge import SYSTEM_PROMPT

    filled = SYSTEM_PROMPT.format(model_checks=model_check_prompt())

    assert "metric_identity" in filled
    assert "may not compute" in filled


# --- clarification handling ---------------------------------------------------


def test_one_clarification_is_confirmed_and_continued(monkeypatch: pytest.MonkeyPatch) -> None:
    """Observed live: the agent found a viable path, then stopped for permission with no
    human in the lane. Unconfirmed, that workspace contributes nothing."""
    from gd_agents.a2a.client import A2ALane
    from gd_agents.transport import Host

    asking = completed_task()
    asking["result"]["status"]["state"] = "input-required"
    asking["result"]["status"]["message"]["parts"][0]["text"] = "Should I use these fields?"
    asking["result"]["artifacts"] = []

    sent: list[str] = []

    def respond(self: object, path: str, body: dict, **kwargs: object) -> dict:
        sent.append(body["params"]["message"]["parts"][0]["text"])
        return asking if len(sent) == 1 else completed_task()

    lane = A2ALane(host=Host(url="https://example.invalid", token="t"), workspace="w")
    monkeypatch.setattr(type(lane.host), "post", respond)

    answer = lane.ask("rank campaigns by spend")

    assert answer.shape.returned_data, "the confirmed answer should count as data"
    assert answer.round_trips == 2
    assert "no human available" in sent[1]
    assert "confirming an assumption" in (answer.shape.population or "")


def test_confirmation_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Off is honest but useless in a fan-out, so it has to be a deliberate choice."""
    from gd_agents.a2a.client import A2ALane
    from gd_agents.transport import Host

    asking = completed_task()
    asking["result"]["status"]["state"] = "input-required"
    asking["result"]["artifacts"] = []

    lane = A2ALane(
        host=Host(url="https://example.invalid", token="t"),
        workspace="w",
        confirm_clarifications=False,
    )
    monkeypatch.setattr(type(lane.host), "post", lambda *a, **k: asking)

    answer = lane.ask("q")

    assert answer.round_trips == 1
    assert not answer.shape.returned_data


# --- session and the enrich path ----------------------------------------------


def turn_of(*answers: Answer):  # type: ignore[no-untyped-def]
    from gd_agents.orchestrator.session import Turn

    return Turn(
        question="q",
        workspaces=tuple(a.workspace for a in answers),
        reply="r",
        answers=answers,
    )


def test_a_failed_retry_does_not_overwrite_a_good_answer() -> None:
    """The point of keeping answers is holding on to what worked. A retry that fails should
    leave the conversation no worse than before it."""
    from gd_agents.orchestrator.session import Session

    session = Session()
    session.remember(turn_of(shaped("mkt", numbers=("100",))))
    session.remember(turn_of(shaped("mkt", error="boom")))

    assert session.answers["mkt"].numbers == ("100",)
    assert session.answers["mkt"].ok()


def test_a_bad_answer_is_recorded_where_there_was_nothing() -> None:
    from gd_agents.orchestrator.session import Session

    session = Session()
    session.remember(turn_of(shaped("mkt", error="boom")))

    assert "mkt" in session.answers
    assert not session.answers["mkt"].ok()


def test_contexts_are_per_lane_and_never_shared() -> None:
    """A workspace engaged for the first time on turn three has no prior turn to resume, and
    handing it another workspace's context would be worse than handing it none."""
    from gd_agents.orchestrator.session import Session

    session = Session(contexts={"mkt": "ctx-mkt"})

    assert session.context_for(("mkt", "cust")) == {"mkt": "ctx-mkt"}


def test_enrichable_names_lanes_that_contributed_nothing() -> None:
    """Failed and empty are different to a reader and identical to a retry."""
    from gd_agents.orchestrator.session import Session

    session = Session()
    session.remember(turn_of(shaped("a"), shaped("b", error="x"), shaped("c", data=False)))

    assert set(session.enrichable()) == {"b", "c"}


def test_the_union_keeps_answers_that_were_not_re_asked() -> None:
    """This is what makes enrichment cheap: retrying one lane costs one call, not four."""
    from gd_agents.orchestrator.session import Session

    session = Session()
    session.remember(turn_of(shaped("mkt", numbers=("100",)), shaped("cust", error="boom")))

    fresh = (shaped("cust", numbers=("27",)),)
    union = session.union_for(fresh)

    assert {a.workspace for a in union} == {"mkt", "cust"}
    assert next(a for a in union if a.workspace == "cust").numbers == ("27",)


def test_enrich_refuses_an_empty_session() -> None:
    from gd_agents.orchestrator.run import enrich
    from gd_agents.orchestrator.session import Session

    with pytest.raises(ValueError, match="no turns"):
        enrich(plan_registry(), {}, Session())


def test_enrich_re_asks_only_the_missing_lane() -> None:
    from gd_agents.orchestrator.run import enrich
    from gd_agents.orchestrator.session import Session

    asked: list[str] = []

    class Recording:
        def __init__(self, workspace: str) -> None:
            self.workspace = workspace

        def describe(self) -> str:
            return ""

        def ask(self, question: str, *, context_id: str | None = None) -> Answer:
            asked.append(self.workspace)
            return shaped(self.workspace, numbers=("27",))

    session = Session()
    session.remember(turn_of(shaped("mkt", numbers=("100",)), shaped("cust", error="boom")))

    run = enrich(
        plan_registry(),
        {"mkt": Recording("mkt"), "cust": Recording("cust")},
        session,
        client=FakeClient("Spend 100 alongside NPS 27."),
        model="m",
    )

    assert asked == ["cust"], "an enrich that re-asks a working lane wastes a call"
    assert run.enriched == ("cust",)
    assert {a.workspace for a in run.merged.answers} == {"mkt", "cust"}


def test_enrich_reuses_the_earlier_sub_question_verbatim() -> None:
    """Re-planning would risk a differently worded sub-question, making the retry a
    different query and the comparison with the kept answers invalid."""
    from gd_agents.orchestrator.run import enrich
    from gd_agents.orchestrator.session import Session

    seen: list[str] = []

    class Recording:
        workspace = "cust"

        def describe(self) -> str:
            return ""

        def ask(self, question: str, *, context_id: str | None = None) -> Answer:
            seen.append(question)
            return shaped("cust", numbers=("27",))

    failed = Answer(workspace="cust", question="Show NPS by month for Q2", text="", error="boom")
    session = Session()
    session.remember(turn_of(shaped("mkt", numbers=("100",)), failed))

    enrich(plan_registry(), {"cust": Recording()}, session, client=FakeClient("x"), model="m")

    assert seen == ["Show NPS by month for Q2"]


def test_enrich_with_nothing_missing_returns_the_previous_reply() -> None:
    from gd_agents.orchestrator.run import enrich
    from gd_agents.orchestrator.session import Session

    session = Session()
    session.remember(turn_of(shaped("mkt"), shaped("cust")))

    run = enrich(plan_registry(), {}, session)

    assert run.reply() == "r"
    assert run.enriched == ()


def test_a_turn_records_the_context_each_lane_ended_on() -> None:
    """Without it a follow-up starts cold and the agent cannot resolve "those"."""
    from gd_agents.orchestrator.fanout import FanoutReport
    from gd_agents.orchestrator.run import _contexts

    report = FanoutReport(
        answers=(
            Answer(workspace="a", question="q", text="t", context_id="ctx-a"),
            Answer(workspace="b", question="q", text="t"),
        )
    )

    assert _contexts(report) == {"a": "ctx-a"}


def test_orchestrator_tokens_exclude_what_happens_inside_a_workspace() -> None:
    """A2A does not report the agent's own cost. Under MCP that same work lands in this
    number, which is most of what the protocol comparison is about."""
    from gd_agents.orchestrator.merge import Merged
    from gd_agents.orchestrator.plan import Plan
    from gd_agents.orchestrator.run import Run

    run = Run(question="q")
    run.plan = Plan(question="q", tokens_in=1700, tokens_out=300)
    run.merged = Merged(tokens_in=900, tokens_out=400)

    assert run.tokens() == (2600, 700)


# --- the payload: the actual interface ----------------------------------------


def a_run():  # type: ignore[no-untyped-def]
    from gd_agents.orchestrator.checks import run_checks
    from gd_agents.orchestrator.merge import Merged
    from gd_agents.orchestrator.plan import Plan, Step
    from gd_agents.orchestrator.run import Run

    answers = (
        Answer(
            workspace="mkt",
            question="Show spend by month",
            text="spend was 100",
            numbers=("100",),
            artifacts=(
                {
                    "name": "visualization-data",
                    "data": {"formattedRows": [{"m": "2026-04", "v": "100"}]},
                },
            ),
            latency_ms=1200,
            shape=Shape(grain="month", time_from="-5..0 MONTH", time_to="-5..0 MONTH"),
        ),
        Answer(workspace="cust", question="Show NPS by month", text="", error="boom"),
    )
    run = Run(question="did spend move satisfaction?", total_ms=3400)
    run.plan = Plan(
        question=run.question,
        steps=(Step("mkt", "Show spend by month", "spend lives here"), Step("cust", "Show NPS by month")),
        reasoning="needs both",
        combine_on="month",
        tokens_in=1700,
        tokens_out=300,
    )
    run.lanes.answers = answers
    run.lanes.wall_ms = 2000
    run.merged = Merged(text="reply", checks=run_checks(list(answers)), combinable=False, answers=answers)
    return run


def test_the_payload_carries_the_decomposition_not_just_the_route() -> None:
    """A host that only learns which workspaces were called cannot show what made this
    federation rather than broadcast."""
    payload = a_run().payload()

    assert [w["id"] for w in payload["routing"]["workspaces"]] == ["mkt", "cust"]
    assert payload["routing"]["workspaces"][0]["question"] == "Show spend by month"
    assert payload["routing"]["combine_on"] == "month"


def test_the_payload_attributes_every_lane_whatever_the_merge_said() -> None:
    """Attribution is structural: each lane stays addressable even if the merge paraphrased
    or refused."""
    lanes = {lane["workspace"]: lane for lane in a_run().payload()["lanes"]}

    assert lanes["mkt"]["text"] == "spend was 100"
    assert lanes["mkt"]["grain"] == "month"
    assert lanes["cust"]["ok"] is False
    assert lanes["cust"]["error"] == "boom"


def test_the_payload_passes_artifacts_through_uninterpreted() -> None:
    """They are GoodData-specific DataParts. A host renders or ignores them — which is the
    product question, so they must arrive whole."""
    artifacts = a_run().payload()["lanes"][0]["artifacts"]

    assert artifacts[0]["name"] == "visualization-data"
    assert artifacts[0]["data"]["formattedRows"][0]["v"] == "100"


def test_the_payload_reports_checks_and_timings_for_the_reader() -> None:
    payload = a_run().payload()

    assert {c["check"] for c in payload["checks"]} >= {"lane_completeness", "shared_dimension"}
    assert payload["timings"]["total_ms"] == 3400
    assert payload["timings"]["fanout_wall_ms"] == 2000
    assert payload["tokens"] == {"in": 1700, "out": 300}


def test_the_payload_is_json_serialisable() -> None:
    """It crosses HTTP, so a dataclass leaking into it breaks the page rather than a test."""
    import json

    assert json.loads(json.dumps(a_run().payload()))["question"]


def test_the_page_reads_only_the_payload() -> None:
    """The page must not depend on anything the interface does not carry, or the demo shows
    more than a host could."""
    from gd_agents.server.app import PAGE

    html = PAGE.read_text(encoding="utf-8")
    payload = a_run().payload()

    for key in ("routing", "lanes", "checks", "timings", "tokens", "reply", "combinable"):
        assert key in payload
        assert key in html, f"the page never reads {key}"
    assert "cdn" not in html.lower(), "no CDN: the page must work with no network"
    assert "<script src" not in html, "no external script"


# --- provenance compared numerically, not textually ---------------------------


def test_the_same_number_written_differently_is_not_invention() -> None:
    """Found live: a lane returned `3,995.00`, the merge wrote `3,995`, and the first version
    of this check — which compared normalised strings — rejected a perfectly honest
    single-lane answer."""
    from gd_agents.orchestrator.checks import check_provenance

    lanes = [shaped("ecom", numbers=("3,995.00",))]

    assert check_provenance("Last month we took 3,995 online orders.", lanes).ok()


def test_numeric_comparison_still_catches_a_cross_workspace_ratio() -> None:
    """Loosening the comparison must not cost the check its teeth."""
    from gd_agents.orchestrator.checks import check_provenance

    lanes = [shaped("mkt", numbers=("11944.45",)), shaped("cust", numbers=("27.04",))]

    assert not check_provenance("Cost per NPS point was 441.73.", lanes).ok()


def test_rounding_a_lane_value_is_still_caught() -> None:
    """Rounding 11,944.45 to 11,944 changes the value, however innocuous it looks."""
    from gd_agents.orchestrator.checks import check_provenance

    lanes = [shaped("mkt", numbers=("11,944.45",))]

    assert not check_provenance("Spend was 11,944.", lanes).ok()


def test_a_single_lane_is_not_told_it_could_not_be_combined() -> None:
    """One lane has nothing to combine with. Saying otherwise implies a failure that did not
    happen."""
    from gd_agents.orchestrator.checks import run_checks
    from gd_agents.orchestrator.merge import separate_answers

    lanes = [shaped("ecom")]
    text = separate_answers("q", lanes, run_checks(lanes))

    assert "could not be combined" not in text
    assert text.startswith("From a single workspace")


# --- input-required reaches the caller ---------------------------------------
# A workspace agent can stop mid-task and ask. Auto-confirming is the orchestrator guessing
# on the user's behalf, which is right in an unattended fan-out and wrong when somebody is
# watching. Both paths have to exist, and the third state has to survive to the payload.


class FakeHost:
    """Hands back prepared Tasks in order, so a multi-round-trip lane can be exercised
    without monkeypatching the transport."""

    def __init__(self, *payloads: dict) -> None:
        self.payloads = list(payloads)
        self.sent: list[str] = []

    def post(self, path: str, body: dict, **kwargs: object) -> dict:
        self.sent.append(body["params"]["message"]["parts"][0]["text"])
        return self.payloads[min(len(self.sent) - 1, len(self.payloads) - 1)]

    def get(self, path: str, **kwargs: object) -> dict:
        return {}


def clarifying_task() -> dict:
    return {
        "result": {
            "kind": "task",
            "contextId": "ctx-ask",
            "status": {
                "state": "input-required",
                "message": {
                    "role": "agent",
                    "parts": [
                        {
                            "kind": "text",
                            "text": (
                                "I found the spend metric but it has no campaign field. "
                                "Shall I use {attribute/campaign_name} instead?"
                            ),
                        }
                    ],
                },
            },
        }
    }


def test_a_lane_that_asks_is_neither_an_answer_nor_a_failure() -> None:
    from gd_agents.a2a.client import A2ALane

    lane = A2ALane(host=FakeHost(clarifying_task()), workspace="mkt", confirm_clarifications=False)
    answer = lane.ask("Rank campaigns by spend")

    assert answer.ok(), "it did not fail — it asked"
    assert answer.input_required
    assert not answer.shape.returned_data, "a question is not data to merge"
    assert "campaign field" in answer.text


def test_auto_confirming_clears_the_pending_flag() -> None:
    """The unattended path. The lane consents once, on the same conversation, and the answer
    that comes back is a real one."""
    from gd_agents.a2a.client import A2ALane

    host = FakeHost(clarifying_task(), completed_task())
    lane = A2ALane(host=host, workspace="mkt", confirm_clarifications=True)
    answer = lane.ask("Rank campaigns by spend")

    assert not answer.input_required
    assert answer.shape.returned_data
    assert answer.round_trips == 2


def test_the_payload_carries_what_is_waiting_on_a_human() -> None:
    """A host with a person in front of it can put the question to them; one without ignores
    this list. Either way it must be in the interface, not only on our page."""
    from gd_agents.orchestrator.fanout import FanoutReport
    from gd_agents.orchestrator.run import Run

    run = Run(question="q")
    run.lanes = FanoutReport(
        answers=(
            Answer(
                workspace="mkt",
                question="Rank campaigns by spend",
                text="Shall I use campaign name?",
                input_required=True,
                shape=Shape(returned_data=False),
            ),
        )
    )
    payload = run.payload()

    assert payload["pending"] == [
        {
            "workspace": "mkt",
            "question": "Rank campaigns by spend",
            "asks": "Shall I use campaign name?",
        }
    ]
    assert payload["lanes"][0]["input_required"] is True


def test_respond_asks_only_the_lane_that_asked() -> None:
    """The others already answered. Re-asking them costs a full fan-out to change nothing,
    and might return different numbers — making the merge a comparison across two moments."""
    from gd_agents.orchestrator.run import respond
    from gd_agents.orchestrator.session import Session

    asked: list[tuple[str, str, str | None]] = []

    class Recording:
        def __init__(self, workspace: str) -> None:
            self.workspace = workspace

        def describe(self) -> str:
            return ""

        def ask(self, question: str, *, context_id: str | None = None) -> Answer:
            asked.append((self.workspace, question, context_id))
            return shaped(self.workspace, numbers=("27",))

    pending = Answer(
        workspace="cust",
        question="Show NPS by month for Q2",
        text="Which NPS metric did you mean?",
        input_required=True,
        shape=Shape(returned_data=False),
    )
    session = Session()
    session.remember(turn_of(shaped("mkt", numbers=("100",)), pending), contexts={"cust": "ctx-9"})

    run = respond(
        {"mkt": Recording("mkt"), "cust": Recording("cust")},
        session,
        "cust",
        "The overall one, monthly.",
        client=FakeClient("Spend 100 alongside NPS 27."),
        model="m",
    )

    assert asked == [("cust", "The overall one, monthly.", "ctx-9")]
    assert run.enriched == ("cust",)
    assert {a.workspace for a in run.merged.answers} == {"mkt", "cust"}


def test_respond_restores_the_original_sub_question() -> None:
    """"The overall one, monthly" is not a question. Left in place it would read as nonsense
    in an attribution line, and the merge needs to know what was actually asked."""
    from gd_agents.orchestrator.run import respond
    from gd_agents.orchestrator.session import Session

    class Recording:
        workspace = "cust"

        def describe(self) -> str:
            return ""

        def ask(self, question: str, *, context_id: str | None = None) -> Answer:
            return replace(shaped("cust", numbers=("27",)), question=question)

    pending = Answer(
        workspace="cust",
        question="Show NPS by month for Q2",
        text="Which metric?",
        input_required=True,
        shape=Shape(returned_data=False),
    )
    session = Session()
    session.remember(turn_of(pending))

    run = respond(
        {"cust": Recording()}, session, "cust", "The overall one.", client=FakeClient("x"), model="m"
    )

    assert [a.question for a in run.merged.answers] == ["Show NPS by month for Q2"]


def test_respond_refuses_a_workspace_with_no_lane() -> None:
    from gd_agents.orchestrator.run import respond
    from gd_agents.orchestrator.session import Session

    session = Session()
    session.remember(turn_of(shaped("mkt")))

    with pytest.raises(ValueError, match="no lane configured"):
        respond({}, session, "nope", "hi")


# --- the progress feed --------------------------------------------------------
# A turn takes 30-120 seconds, and one spinner for the whole of it hides the interesting
# part. The feed is narration only: the payload remains the interface.


def test_a_turn_narrates_the_router_the_lanes_and_the_merge() -> None:
    from gd_agents.orchestrator.run import ask

    seen: list[tuple[str, dict]] = []

    class Quiet:
        def __init__(self, workspace: str) -> None:
            self.workspace = workspace

        def describe(self) -> str:
            return ""

        def ask(self, question: str, *, context_id: str | None = None) -> Answer:
            return shaped(self.workspace, numbers=("100",))

    ask(
        "did spend move satisfaction?",
        plan_registry(),
        {"mkt": Quiet("mkt"), "cust": Quiet("cust")},
        client=FakeClient(
            '{"workspaces":[{"id":"mkt","question":"Show spend by month"},'
            '{"id":"cust","question":"Show NPS by month"}],"combine_on":"month"}',
            "Spend 100 alongside NPS 100.",
        ),
        model="m",
        observe=lambda kind, detail: seen.append((kind, detail)),
    )

    kinds = [kind for kind, _ in seen]
    assert kinds[0] == "planning"
    assert kinds[-1] == "done"
    for expected in ("plan", "lane_start", "lane_done", "merge_start", "checks"):
        assert expected in kinds, f"the feed never reports {expected}"
    # The last event is the whole payload, so a streaming host and a blocking one end up
    # holding exactly the same thing.
    assert seen[-1][1]["payload"]["reply"]
    assert {d["workspace"] for k, d in seen if k == "lane_done"} == {"mkt", "cust"}


def test_a_broken_observer_does_not_cost_the_answer() -> None:
    """It is caller-supplied code running inside a fan-out thread. A front end with a broken
    renderer should lose its progress bar, not the reply."""
    from gd_agents.orchestrator.events import emit

    def explode(kind: str, detail: dict) -> None:
        raise RuntimeError("renderer is on fire")

    emit(explode, "plan", workspaces=[])  # must not raise


def test_the_lane_reports_each_round_trip() -> None:
    """One POST, or a POST plus a confirmation, or a retry after a 502 — the shape of the
    wait is the thing worth showing during 90 seconds of silence."""
    from gd_agents.a2a.client import A2ALane

    steps: list[str] = []
    lane = A2ALane(
        host=FakeHost(clarifying_task(), completed_task()),
        workspace="mkt",
        observe=lambda kind, detail: steps.append(str(detail.get("step"))),
    )
    lane.ask("Rank campaigns by spend")

    assert steps[0] == "message/send"
    assert "input-required" in steps
    assert steps[-1] == "read"


# --- the page and the script --------------------------------------------------


def test_the_page_renders_the_agents_own_chart_type() -> None:
    """The agent already decided this was a line chart of Total Campaign Spend by month. A
    page that re-guesses from the rows throws that decision away."""
    from gd_agents.server.app import PAGE

    html = PAGE.read_text(encoding="utf-8")

    assert "visualizationId" in html, "the two artifacts must be paired by id"
    for key in ("line_chart", "formattedRows", "columns", "pending", "input_required"):
        assert key in html, f"the page never reads {key}"


def test_the_script_is_served_as_the_pages_prompts() -> None:
    """The runbook, the routing measurement and the demo buttons are one file, so they cannot
    drift apart."""
    from gd_agents.server.app import script_payload

    payload = script_payload()

    assert len(payload["questions"]) >= 20, "the demo needs a full bank of prompts"
    assert all(q["question"] and q["expect"] for q in payload["questions"])
    assert payload["conversations"], "follow-ups are half the point of a conversation"


def test_a_missing_script_costs_the_buttons_and_nothing_else() -> None:
    from gd_agents.server.app import script_payload

    assert script_payload(Path("config/does-not-exist.yaml")) == {"questions": [], "conversations": []}


# --- the charts, actually executed ---------------------------------------------
# The rendering is the one part of this that cannot be checked by reading the payload, and
# it is the part a viewer is judged on. So the page's chart functions are pulled out and run
# against the artifact shapes a live agent really returns. Skipped where node is absent —
# a missing tool must not read as a passing test.


CHART_HARNESS = """
const esc = s => String(s == null ? '' : s).replace(/&/g,'&amp;')
  .replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
function pill(cls, text){ return `<span class="pill ${cls}">${esc(text)}</span>`; }
function colour(){ return 'var(--w0)'; }
%s
const out = {};
function draw(name, type, title, columns, rows, formattedRows) {
  out[name] = charts({workspace: 'w', artifacts: [
    {name: 'visualization', data: {type, title, id: name}},
    {name: 'visualization-data', data: {visualizationId: name, columns, rows,
      formattedRows, rowCount: rows.length}},
  ]})[0] || '';
}
const MONTHS = ['2026-04','2026-05','2026-06','2026-07','2026-08','2026-09'];
const NPS = [32.31, 35.20, 55.17, 41.00, 38.40, 44.10];
draw('line', 'line_chart', 'Average Total NPS Score by Month',
  [{name:'Month/Year',type:'attribute'},{name:'Average Total NPS Score',type:'metric',format:'#,##0.00'}],
  MONTHS.map((m,i) => ({'Month/Year': m, 'Average Total NPS Score': NPS[i]})),
  MONTHS.map((m,i) => ({'Month/Year': m, 'Average Total NPS Score': NPS[i].toFixed(2)})));
draw('bars', 'bar_chart', 'Top stores by footfall',
  [{name:'Store',type:'attribute'},{name:'Footfall',type:'metric',format:'#,##0'}],
  [{Store:'A',Footfall:900},{Store:'B',Footfall:450}],
  [{Store:'A',Footfall:'900'},{Store:'B',Footfall:'450'}]);
draw('headline', 'headline', 'Online orders',
  [{name:'Online Orders',type:'metric',format:'#,##0'}],
  [{'Online Orders':3995}], [{'Online Orders':'3,995'}]);
draw('downgrade', 'scatter_chart', 'A scatter with one metric',
  [{name:'Month',type:'attribute'},{name:'Spend',type:'metric',format:'#,##0'}],
  [{Month:'A',Spend:1},{Month:'B',Spend:2}], null);
draw('empty', 'line_chart', 'Nothing came back',
  [{name:'Month',type:'attribute'},{name:'Spend',type:'metric'}], [], null);
console.log(JSON.stringify(out));
"""


def rendered_charts() -> dict[str, str]:
    """Run the page's chart code in node against real artifact shapes."""
    import json
    import re
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed; the chart rendering cannot be executed here")

    from gd_agents.server.app import PAGE

    script = re.search(r"<script>(.*)</script>", PAGE.read_text(encoding="utf-8"), re.S)
    assert script, "the page has no script block"
    # Everything from the chart section down is self-contained; above it is fetch and DOM.
    body = script.group(1)
    charts = body[body.index("// ── charts") :]

    finished = subprocess.run(
        [node, "-e", CHART_HARNESS % charts], capture_output=True, text=True, timeout=30
    )
    assert finished.returncode == 0, finished.stderr
    return dict(json.loads(finished.stdout))


def test_a_line_chart_is_drawn_as_a_line() -> None:
    """Six months of NPS, as the live agent returns them: a declared `line_chart`, a title,
    and formatted rows. The agent already made this decision and the page must honour it."""
    drawn = rendered_charts()["line"]

    assert "Average Total NPS Score by Month" in drawn, "the agent's own title"
    assert re.search(r'<polyline class="ln" points="[\d., ]+"', drawn), "no line was drawn"
    assert drawn.count('<circle class="pt"') == 6, "one mark per month"
    assert "NaN" not in drawn, "a NaN in a coordinate silently collapses the chart"


def test_a_bar_chart_is_drawn_to_scale() -> None:
    drawn = rendered_charts()["bars"]

    assert re.findall(r"width:([\d.]+)%", drawn) == ["100.0", "50.0"]


def test_a_single_value_is_drawn_as_a_headline_with_its_format_kept() -> None:
    """`3,995` not `3995`: the workspace applied a number format and re-deriving it here
    would quietly disagree with the answer text above the chart."""
    assert 'class="headline">3,995' in rendered_charts()["headline"]


def test_a_chart_the_shape_cannot_support_falls_back_and_says_so() -> None:
    """A scatter needs two metrics. Dropping to a table is right; doing it silently reads as
    the agent having ignored the request, which is the one thing this is meant to disprove."""
    drawn = rendered_charts()["downgrade"]

    assert "<table" in drawn
    assert "shown as a table" in drawn


def test_no_rows_says_no_rows() -> None:
    assert "no rows returned" in rendered_charts()["empty"]


# --- a lane that returns two charts --------------------------------------------
# Found live 2026-09-21. The plan asked marketing for a campaign ranking *and* a monthly
# series, the agent returned both, and the shape read only the first — so the merge refused a
# pair that agreed on month. Answering more fully than the minimum must not be a reason to
# refuse.


def two_chart_task() -> dict:
    def viz(identifier: str, grain: str, granularity: str, frm: int, to: int) -> dict:
        return {
            "name": "visualization",
            "parts": [
                {
                    "kind": "data",
                    "data": {
                        "id": identifier,
                        "type": "bar_chart",
                        "view_by": ["d"],
                        "query": {
                            "fields": {"d": {"using": grain}},
                            "filter_by": {
                                "w": {
                                    "type": "date_filter",
                                    "granularity": granularity,
                                    "from": frm,
                                    "to": to,
                                }
                            },
                        },
                    },
                }
            ],
        }

    task = completed_task()
    task["result"]["artifacts"] = [
        viz("ranking", "label/sql_campaign_roi.campaign_id", "QUARTER", -1, -1),
        viz("series", "label/transaction_date.month", "MONTH", -5, 0),
    ]
    return task


def test_every_chart_a_lane_returned_shapes_the_answer() -> None:
    from gd_agents.a2a.client import data_artifacts, shape_from_artifacts

    shape = shape_from_artifacts(data_artifacts(two_chart_task()))

    assert shape.grains == ("campaign_id", "month")
    assert shape.windows == ("-1..-1 QUARTER", "-5..0 MONTH")
    assert shape.grain == "campaign_id", "the first chart still reads as the headline shape"


def test_two_lanes_sharing_one_grain_may_be_combined() -> None:
    """marketing {campaign_id, month} against customer {month} do share a key — month."""
    from gd_agents.orchestrator.checks import run_checks

    marketing = replace(
        shaped("mkt"),
        shape=Shape(
            grains=("campaign_id", "month"),
            windows=("-1..-1 QUARTER", "-5..0 MONTH"),
            units="USD",
        ),
    )
    customer = replace(
        shaped("cust"),
        shape=Shape(grains=("month",), windows=("-5..0 MONTH",), units="USD"),
    )
    report = run_checks([marketing, customer])

    assert report.combinable()
    reasons = " ".join(r.reason for r in report.results)
    assert "common grain month" in reasons
    assert "also returned campaign_id" in reasons, "the reader must know which part compares"


def test_an_overlap_is_still_required() -> None:
    """Looking for an overlap must not become looking for an excuse."""
    from gd_agents.orchestrator.checks import run_checks

    a = replace(shaped("a"), shape=Shape(grains=("campaign_id",), windows=("-1..-1 QUARTER",)))
    b = replace(shaped("b"), shape=Shape(grains=("store_id",), windows=("-1..-1 QUARTER",)))

    assert not run_checks([a, b]).combinable()


def test_one_windows_two_ends_are_not_two_windows() -> None:
    """April-September and April-June share a start date and no period. Reading `time_from`
    and `time_to` as independent values let exactly that pass."""
    from gd_agents.orchestrator.checks import run_checks

    report = run_checks([shaped("a", to="2026-09-30"), shaped("b", to="2026-06-30")])

    assert not report.combinable()
    assert "no shared period" in report.reasons()


# --- object ids resolved to the labels the same response carried ---------------
# The agent writes "{metric/metric_l1_total_campaign_spend} did not have a campaign
# breakdown" into its prose while the data artifact beside it calls that same object
# "Total Campaign Spend". Showing the id to a reader is a rendering failure we can fix
# without inventing anything.


def two_chart_artifacts() -> tuple[dict, ...]:
    from gd_agents.a2a.client import data_artifacts

    task = completed_task()
    task["result"]["artifacts"] = [
        {
            "name": "visualization",
            "parts": [
                {
                    "kind": "data",
                    "data": {
                        "id": "series",
                        "type": "line_chart",
                        "metrics": ["m_spend"],
                        "view_by": ["d_month"],
                        "query": {
                            "fields": {
                                "m_spend": {"using": "metric/metric_l1_total_campaign_spend"},
                                "d_month": {"using": "label/transaction_date.month"},
                            },
                            "filter_by": {
                                "w": {
                                    "type": "date_filter",
                                    "granularity": "MONTH",
                                    "from": -5,
                                    "to": 0,
                                }
                            },
                        },
                    },
                }
            ],
        },
        {
            "name": "visualization-data",
            "parts": [
                {
                    "kind": "data",
                    "data": {
                        "visualizationId": "series",
                        "columns": [
                            {"name": "Month/Year", "type": "attribute"},
                            {"name": "Total Campaign Spend", "type": "metric", "format": "#,##0.00"},
                        ],
                        "formattedRows": [
                            {"Month/Year": "2026-04", "Total Campaign Spend": "11,944.45"},
                            {"Month/Year": "2026-05", "Total Campaign Spend": "9,726.62"},
                        ],
                    },
                }
            ],
        },
    ]
    return data_artifacts(task)


def test_an_object_id_becomes_the_label_the_workspace_gave_it() -> None:
    from gd_agents.artifacts import label_map, resolve_placeholders

    labels = label_map(two_chart_artifacts())
    text = "{metric/metric_l1_total_campaign_spend} by {label/transaction_date.month} returned:"

    assert resolve_placeholders(text, labels) == "Total Campaign Spend by Month/Year returned:"


def test_an_id_with_no_label_is_left_exactly_as_written() -> None:
    """A plausible-looking label derived from an identifier would be a guess presented as a
    fact. Leaving it visible is ugly and true, and it is on the gap list."""
    from gd_agents.artifacts import label_map, resolve_placeholders, unresolved

    text = "I could use {attribute/sql_campaign_roi.campaign_id} instead."
    out = resolve_placeholders(text, label_map(two_chart_artifacts()))

    assert out == text
    assert unresolved(out) == ("{attribute/sql_campaign_roi.campaign_id}",)


def test_the_lane_resolves_ids_before_the_answer_leaves_it() -> None:
    """So every host gets readable prose, not just our page."""
    from gd_agents.a2a.client import A2ALane

    lane = A2ALane(host=FakeHost(spend_task()), workspace="mkt")
    answer = lane.ask("Show spend by month")

    assert "Total Campaign Spend" in answer.text
    assert "{metric/" not in answer.text


def spend_task() -> dict:
    task = completed_task()
    task["result"]["status"]["message"]["parts"][0]["text"] = (
        "Created a line chart showing {metric/metric_l1_total_campaign_spend} by month."
    )
    task["result"]["artifacts"] = [
        {
            "name": "visualization",
            "parts": [
                {
                    "kind": "data",
                    "data": {
                        "id": "series",
                        "metrics": ["m_spend"],
                        "view_by": ["d_month"],
                        "query": {
                            "fields": {
                                "m_spend": {"using": "metric/metric_l1_total_campaign_spend"},
                                "d_month": {"using": "label/transaction_date.month"},
                            }
                        },
                    },
                }
            ],
        },
        {
            "name": "visualization-data",
            "parts": [
                {
                    "kind": "data",
                    "data": {
                        "visualizationId": "series",
                        "columns": [
                            {"name": "Month/Year", "type": "attribute"},
                            {"name": "Total Campaign Spend", "type": "metric"},
                        ],
                        "formattedRows": [{"Month/Year": "2026-04", "Total Campaign Spend": "11,944.45"}],
                    },
                }
            ],
        },
    ]
    return task


# --- the rows behind the answer -----------------------------------------------
# The merge narrates a comparison; a reader wants the two series that sentence was read off.
# Alignment on a shared grain, never a join.


def charted(workspace: str, grain_using: str, key: str, metric: str, rows: list[dict]) -> Answer:
    identifier = f"{workspace}-{metric}"
    return Answer(
        workspace=workspace,
        question="q",
        text="t",
        shape=Shape(grains=(grain_using.rsplit(".", 1)[-1],), units="x"),
        artifacts=(
            {
                "name": "visualization",
                "data": {
                    "id": identifier,
                    "metrics": ["m"],
                    "view_by": ["d"],
                    "query": {"fields": {"m": {"using": f"metric/{metric}"}, "d": {"using": grain_using}}},
                },
            },
            {
                "name": "visualization-data",
                "data": {
                    "visualizationId": identifier,
                    "columns": [
                        {"name": key, "type": "attribute"},
                        {"name": metric, "type": "metric"},
                    ],
                    "formattedRows": rows,
                },
            },
        ),
    )


def test_two_lanes_become_one_table_on_the_shared_grain() -> None:
    from gd_agents.orchestrator.align import align

    spend = charted(
        "mkt",
        "label/transaction_date.month",
        "Month/Year",
        "Total Campaign Spend",
        [
            {"Month/Year": "2026-04", "Total Campaign Spend": "11,944.45"},
            {"Month/Year": "2026-05", "Total Campaign Spend": "9,726.62"},
        ],
    )
    nps = charted(
        "cust",
        "label/transaction_date.month",
        "Month/Year",
        "Average Total NPS Score",
        [
            {"Month/Year": "2026-04", "Average Total NPS Score": "32.31"},
            {"Month/Year": "2026-05", "Average Total NPS Score": "35.20"},
        ],
    )
    table = align([spend, nps], "month").payload()

    assert table["grain"] == "month"
    assert [c["workspace"] for c in table["columns"]] == ["mkt", "cust"]
    assert table["rows"][0] == {"key": "2026-04", "cells": ["11,944.45", "32.31"]}


def test_a_period_one_lane_did_not_cover_is_blank_not_zero() -> None:
    """A zero would read as a measured value of nothing, which is a different claim."""
    from gd_agents.orchestrator.align import align

    long = charted(
        "mkt",
        "label/transaction_date.month",
        "Month/Year",
        "Spend",
        [{"Month/Year": "2026-04", "Spend": "1"}, {"Month/Year": "2026-05", "Spend": "2"}],
    )
    short = charted(
        "cust", "label/transaction_date.month", "Month/Year", "NPS", [{"Month/Year": "2026-04", "NPS": "9"}]
    )
    rows = align([long, short], "month").payload()["rows"]

    assert rows[1] == {"key": "2026-05", "cells": ["2", ""]}


def test_a_chart_at_another_grain_stays_out_of_the_table() -> None:
    """A lane's campaign ranking has no place in a monthly table — putting it there would
    imply a correspondence that does not exist."""
    from gd_agents.orchestrator.align import align

    ranking = charted(
        "mkt",
        "label/sql_campaign_roi.campaign_id",
        "Campaign ID",
        "Total Spend",
        [{"Campaign ID": "c1", "Total Spend": "2,560.34"}],
    )
    series = charted(
        "cust",
        "label/transaction_date.month",
        "Month/Year",
        "NPS",
        [{"Month/Year": "2026-04", "NPS": "9"}, {"Month/Year": "2026-05", "NPS": "8"}],
    )
    table = align([ranking, series], "month")

    assert [c.name for c in table.columns] == ["NPS"]
    assert not table.usable(), "one lane's series is not a comparison"


def test_no_table_when_the_lanes_do_not_combine() -> None:
    """A table of two series asserts they are comparable — the claim the checks gate."""
    from gd_agents.orchestrator.merge import Merged
    from gd_agents.orchestrator.run import Run

    run = Run(question="q")
    run.merged = Merged(combinable=False)

    assert run.payload()["table"] is None


# --- markdown, executed -------------------------------------------------------
# The agents answer in markdown. Rendering it as plain text puts literal ** on screen; the
# fix is a renderer, and a renderer handed agent text is an injection surface.


MD_HARNESS = """
const esc = s => String(s == null ? '' : s).replace(/&/g,'&amp;')
  .replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
%s
const lane = [
 'I created two charts.',
 '',
 '- **Campaign ranking:** returned one row with a blank campaign ID: **2,560.34**.',
 '- **Monthly spend:** Total Campaign Spend by month returned:',
 '  - **2026-04:** 11,944.45',
 '  - **2026-05:** 9,726.62',
 '',
 'I could not use fiscal date here.',
].join('\\n');
console.log(JSON.stringify({
  lane: md(lane),
  nasty: md('<img src=x onerror=alert(1)> **bold** <script>bad()</script>'),
  ids: md('metric_l1_total_campaign_spend and fact_display_impression_000313'),
  italic: md('a *word* here'),
  table: md([
    '| Month | Average Total NPS Score | Total Sentiment Score |',
    '|---|---:|---:|',
    '| 2026-04 | **32.31** | -0.37 |',
    '| 2026-05 | 35.20 | 1.41 |',
  ].join('\\n')),
}));
"""


def rendered_markdown() -> dict[str, str]:
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed; the markdown renderer cannot be executed here")

    from gd_agents.server.app import PAGE

    script = re.search(r"<script>(.*)</script>", PAGE.read_text(encoding="utf-8"), re.S)
    assert script
    body = script.group(1)
    start = body.index("// ── the markdown the agents write")
    end = body.index("// ── workspace strip")

    finished = subprocess.run(
        [node, "-e", MD_HARNESS % body[start:end]], capture_output=True, text=True, timeout=30
    )
    assert finished.returncode == 0, finished.stderr
    return dict(json.loads(finished.stdout))


def test_a_lanes_markdown_reaches_the_screen_as_formatting() -> None:
    drawn = rendered_markdown()["lane"]

    assert "**" not in drawn, "literal asterisks are the bug"
    assert drawn.count("<b>") == 5
    assert re.search(r"<li>[^<]*<b>Monthly spend:</b>[\s\S]*?<ul><li>", drawn), (
        "the sub-list must sit inside the item it belongs to, not beside it"
    )
    assert drawn.count("<ul>") == drawn.count("</ul>")
    assert drawn.count("<li>") == drawn.count("</li>")


def test_agent_text_cannot_inject_markup() -> None:
    """A renderer handed text from a remote agent is an injection surface. Escape first,
    then introduce only the handful of tags the renderer owns."""
    drawn = rendered_markdown()["nasty"]

    assert "<img" not in drawn
    assert "<script" not in drawn
    assert "<b>bold</b>" in drawn


def test_underscores_in_object_ids_do_not_become_italics() -> None:
    """Which is why the renderer takes no underscore emphasis: `metric_l1_total_campaign_spend`
    would turn italic halfway through its own name."""
    assert "<i>" not in rendered_markdown()["ids"]
    assert "<i>word</i>" in rendered_markdown()["italic"]


def test_a_markdown_table_from_a_lane_is_drawn_as_a_table() -> None:
    """Seen live: the customer lane answered a six-month series as a pipe table. Rendered as
    paragraphs it is a wall of pipes."""
    drawn = rendered_markdown()["table"]

    assert "<table" in drawn
    assert "|" not in drawn
    assert drawn.count("<tr>") == 3, "header plus two rows"
    assert drawn.count('<td class="num">') == 4, "the ---: columns are numeric"
    assert "<b>32.31</b>" in drawn, "inline markdown inside a cell still renders"
