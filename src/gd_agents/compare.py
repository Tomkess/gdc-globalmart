"""FEAT-014's measurement: the same questions over a2a, mcp (nested) and mcp-flat, tabulated.

One command, three arms, one report in `reports/` — markdown for a reader, JSON for anyone
who wants to recompute. Every figure is read off the `Run` each arm returns, so the harness
adds no reasoning of its own: if a number is wrong here it is wrong in the payload too.

## What each column means

- **tokens in/out** — orchestrator (router + merge, or the flat host) plus MCP sub-agents.
  Under A2A the workspace agent's own model spend is invisible to the caller, so A2A's figure
  is what *the caller* pays, not what the question costs GoodData.
- **latency** — the whole turn, wall clock.
- **workspaces** — the workspaces that answered (a2a/mcp: the router's choice; flat: those the
  host ran `execute_query` against). `routing` compares them to the script's `expect`.
- **round trips** — model turns between sub-question and answer, summed over lanes (A2A: one
  per lane). For flat, the host's turns.
- **catalog tok** — characters of metric/attribute catalogue (`ai_search`, `list_*`,
  `get_workspace_info` output) that entered a model context, over four. Zero for A2A by
  construction.
- **disambiguation** — three concrete counts, summed (each is reported separately in JSON):
  `substituted`: a lane's (or the flat host's) prose says it used another metric than the one
  asked for — "instead of", "substituted", "as a proxy", "closest match". `off_named`: the
  router named a metric in the sub-question, the lane returned metric columns, and none of
  their titles appears in the sub-question — it answered with a different metric than the
  one named. An upper bound: a title written differently also counts. Not applicable to flat,
  which has no sub-question. `cross_workspace`: flat only — an `execute_query` on one
  workspace using a metric id discovered only in another.
- **merge** — `single` (one lane, answered), `combined` (checks passed, merge kept), `separate`
  (checks refused; the reason is in JSON), `rejected` (merge invented a number, or the lane/
  host produced nothing).
- **cost** — tokens priced from `config/prices.yaml`. Absent when the model is not listed.
- **correct** — `unscored` unless the script carries expected answers. It currently carries
  routing expectations only, and a correctness figure invented from those would be routing
  accuracy wearing another column's name.
"""

from __future__ import annotations

import json
import re
import statistics
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from gd_agents.artifacts import chart_pairs, columns_of
from gd_agents.orchestrator.run import Run
from gd_agents.script import Question

DEFAULT_PRICES_PATH = Path("config/prices.yaml")
DEFAULT_REPORTS_DIR = Path("reports")
VARIANTS: tuple[str, ...] = ("a2a", "mcp", "mcp-flat")

#: Prose that admits a substitution. Deliberately phrases, not single words: "instead" alone
#: matches "instead of guessing", which is the model being careful rather than substituting.
SUBSTITUTION = re.compile(
    r"\b(instead of|in place of|substitut\w*|as a proxy|closest (?:available|match|equivalent)"
    r"|used .{0,60}? instead|fell back to|rather than the requested)\b",
    re.IGNORECASE,
)


def load_prices(path: Path = DEFAULT_PRICES_PATH) -> dict[str, tuple[float, float]]:
    if not Path(path).exists():
        return {}
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {
        str(model): (float(price["input"]), float(price["output"]))
        for model, price in (raw.get("per_million_tokens") or {}).items()
    }


def cost(tokens_in: int, tokens_out: int, model: str, prices: dict[str, tuple[float, float]]) -> float | None:
    price = prices.get(model)
    if price is None:
        return None
    return round((tokens_in * price[0] + tokens_out * price[1]) / 1_000_000, 4)


@dataclass
class Disambiguation:
    substituted: int = 0
    off_named: int = 0
    cross_workspace: int = 0

    def total(self) -> int:
        return self.substituted + self.off_named + self.cross_workspace


def returned_metrics(artifacts: Sequence[dict[str, Any]]) -> list[str]:
    """The metric column titles a lane's data artifacts carried."""
    names: list[str] = []
    for _, data in chart_pairs(artifacts):
        names.extend(columns_of(data)[1])
    return names


def disambiguation(
    run: Run, *, host_text: str = "", cross_workspace: int = 0, flat: bool = False
) -> Disambiguation:
    found = Disambiguation(cross_workspace=cross_workspace)
    if flat:
        found.substituted = 1 if SUBSTITUTION.search(host_text or "") else 0
        return found
    for answer in run.lanes.answers:
        if SUBSTITUTION.search(answer.text or ""):
            found.substituted += 1
        metrics = returned_metrics(answer.artifacts)
        asked = (answer.question or "").lower()
        if metrics and asked and not any(name.lower() in asked for name in metrics):
            found.off_named += 1
    return found


@dataclass
class Row:
    """One question, one variant."""

    question: str
    variant: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    workspaces: list[str] = field(default_factory=list)
    expected: list[str] = field(default_factory=list)
    routing_exact: bool = False
    round_trips: int = 0
    lane_round_trips: dict[str, int] = field(default_factory=dict)
    catalog_tokens: int = 0
    disambiguation: dict[str, int] = field(default_factory=dict)
    merge: str = ""
    merge_ok: bool = False
    merge_note: str = ""
    cost_usd: float | None = None
    correct: str = "unscored"
    reply: str = ""
    error: str | None = None


def merge_state(run: Run) -> tuple[str, bool, str]:
    merged = run.merged
    answers = run.lanes.answers
    with_data = run.lanes.with_data()
    if merged.rejected:
        return "rejected", False, merged.rejected
    if len(answers) <= 1:
        return ("single", bool(with_data) and merged.ok(), "")
    if merged.combinable:
        return "combined", merged.ok(), ""
    return "separate", False, merged.checks.reasons()


def measure(
    run: Run,
    question: Question,
    variant: str,
    *,
    model: str,
    prices: dict[str, tuple[float, float]],
    host_turns: int | None = None,
    host_text: str = "",
    cross_workspace: int = 0,
) -> Row:
    orchestrator_in, orchestrator_out = run.tokens()
    lanes_in, lanes_out = run.lanes.total_tokens()
    tokens_in, tokens_out = orchestrator_in + lanes_in, orchestrator_out + lanes_out
    workspaces = [answer.workspace for answer in run.lanes.answers]
    found = disambiguation(
        run, host_text=host_text, cross_workspace=cross_workspace, flat=variant == "mcp-flat"
    )
    state, ok, note = merge_state(run)
    return Row(
        question=question.id,
        variant=variant,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=run.total_ms,
        workspaces=workspaces,
        expected=list(question.expect),
        routing_exact=set(workspaces) == set(question.expect),
        round_trips=host_turns if host_turns is not None else run.lanes.round_trips(),
        lane_round_trips={a.workspace: a.round_trips for a in run.lanes.answers},
        catalog_tokens=sum(a.catalog_chars for a in run.lanes.answers) // 4,
        disambiguation={**asdict(found), "total": found.total()},
        merge=state,
        merge_ok=ok,
        merge_note=note[:300],
        cost_usd=cost(tokens_in, tokens_out, model, prices),
        reply=run.reply()[:1500],
    )


Runner = Callable[[Question], Row]


def run_compare(
    questions: Sequence[Question],
    runners: dict[str, Runner],
    *,
    progress: Callable[[str], None] | None = None,
) -> list[Row]:
    """Every question over every variant. A variant that raises costs its row, not the run."""
    rows: list[Row] = []
    for question in questions:
        for variant, runner in runners.items():
            try:
                row = runner(question)
            except Exception as error:  # noqa: BLE001 - one broken arm must not end the comparison
                row = Row(
                    question=question.id,
                    variant=variant,
                    expected=list(question.expect),
                    error=f"{type(error).__name__}: {error}"[:300],
                )
            rows.append(row)
            if progress:
                progress(line(row))
    return rows


def line(row: Row) -> str:
    if row.error:
        return f"  {row.question:30} {row.variant:9} ERROR {row.error[:90]}"
    return (
        f"  {row.question:30} {row.variant:9} {row.latency_ms / 1000:6.1f}s "
        f"{row.tokens_in:>9,} in {row.tokens_out:>6,} out  rt {row.round_trips:>3}  "
        f"cat {row.catalog_tokens:>7,}  {row.merge}"
    )


def _money(value: float | None) -> str:
    return "—" if value is None else f"${value:.3f}"


def summary(rows: Sequence[Row]) -> list[dict[str, Any]]:
    """Per variant: totals and medians over the rows that ran."""
    out = []
    for variant in dict.fromkeys(row.variant for row in rows):
        ran = [row for row in rows if row.variant == variant and not row.error]
        costs = [row.cost_usd for row in ran if row.cost_usd is not None]
        out.append(
            {
                "variant": variant,
                "questions": len([row for row in rows if row.variant == variant]),
                "errored": len([row for row in rows if row.variant == variant and row.error]),
                "tokens_in": sum(row.tokens_in for row in ran),
                "tokens_out": sum(row.tokens_out for row in ran),
                "median_latency_s": (
                    round(statistics.median([r.latency_ms for r in ran]) / 1000, 1) if ran else None
                ),
                "round_trips": sum(row.round_trips for row in ran),
                "catalog_tokens": sum(row.catalog_tokens for row in ran),
                "disambiguation": sum(row.disambiguation.get("total", 0) for row in ran),
                "routing_exact": sum(1 for row in ran if row.routing_exact),
                "merge_ok": sum(1 for row in ran if row.merge_ok),
                "cost_usd": round(sum(costs), 4) if costs else None,
            }
        )
    return out


def markdown(rows: Sequence[Row], *, model: str, script: str, when: str) -> str:
    lines = [
        "# Protocol comparison: A2A vs MCP (nested) vs MCP (flat)",
        "",
        f"Generated by `gd-agents compare` on {when}. Model `{model}`; questions from `{script}`. "
        "One run per question per variant — a single sample, not a distribution.",
        "",
        "Column definitions are in `src/gd_agents/compare.py`. A2A token and cost figures are what "
        "the *caller* pays; the workspace agent's own model spend is not reported by the protocol.",
        "",
        "## Per variant",
        "",
        "| variant | questions | errored | tokens in | tokens out | median latency | round trips "
        "| catalog tok | disambig. | routing exact | merge ok | est. cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary(rows):
        lines.append(
            f"| {item['variant']} | {item['questions']} | {item['errored']} | {item['tokens_in']:,} "
            f"| {item['tokens_out']:,} | {item['median_latency_s']} s | {item['round_trips']} "
            f"| {item['catalog_tokens']:,} | {item['disambiguation']} | {item['routing_exact']} "
            f"| {item['merge_ok']} | {_money(item['cost_usd'])} |"
        )
    lines += [
        "",
        "## Per question",
        "",
        "| question | variant | tokens in / out | latency | workspaces | routing | round trips "
        "| catalog tok | disambig. (sub/named/cross) | merge | est. cost | correct |",
        "|---|---|---:|---:|---|---|---:|---:|---|---|---:|---|",
    ]
    for row in rows:
        if row.error:
            lines.append(f"| {row.question} | {row.variant} | ERROR: {row.error[:120]} |||||||||| ")
            continue
        d = row.disambiguation
        parts = f"{d.get('substituted', 0)}/{d.get('off_named', 0)}/{d.get('cross_workspace', 0)}"
        lines.append(
            f"| {row.question} | {row.variant} | {row.tokens_in:,} / {row.tokens_out:,} "
            f"| {row.latency_ms / 1000:.1f} s | {', '.join(row.workspaces) or '—'} "
            f"| {'exact' if row.routing_exact else 'miss'} | {row.round_trips} | {row.catalog_tokens:,} "
            f"| {d.get('total', 0)} ({parts}) "
            f"| {row.merge} | {_money(row.cost_usd)} | {row.correct} |"
        )
    notes = [row for row in rows if row.merge_note]
    if notes:
        lines += ["", "## Why merges did not combine", ""]
        lines += [f"- **{row.question} / {row.variant}** — {row.merge_note}" for row in notes]
    return "\n".join(lines) + "\n"


def write_report(
    rows: Sequence[Row],
    *,
    model: str,
    script: str,
    out_dir: Path = DEFAULT_REPORTS_DIR,
    when: str | None = None,
) -> tuple[Path, Path]:
    stamp = when or date.today().isoformat()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"protocol-compare-{stamp}.md"
    json_path = out_dir / f"protocol-compare-{stamp}.json"
    md_path.write_text(markdown(rows, model=model, script=script, when=stamp), encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "generated": stamp,
                "model": model,
                "script": script,
                "summary": summary(rows),
                "rows": [asdict(row) for row in rows],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return md_path, json_path
