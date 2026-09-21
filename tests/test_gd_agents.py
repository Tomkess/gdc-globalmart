# The orchestrator's foundations: the Lane contract, the registry, and the profiler.
from __future__ import annotations

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
