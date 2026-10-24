---
abandoned_at: null
abandoned_reason: null
appetite: m
blocked_at: null
blocked_by: null
confidence: medium
created: '2026-09-21'
cycle: null
depends_on:
- feat-009
enables: []
goal: goal-02
id: feat-014
name: The same multi-workspace orchestrator over MCP instead of A2A, flat and nested,
  so the protocol comparison is measured on identical questions rather than argued
sources: []
status: done
tags: []
updated: '2026-10-24'
---

## Summary

FEAT-009 federates four workspaces over A2A. This runs the same orchestrator over **MCP**, on the
same questions, and reports the difference.

Infobip told us the choice of protocol is ours (Pavel, 27 Aug). Jan Brandejs' preliminary view
after talking to Chris is that A2A fits better. That view is currently an opinion held by informed
people, and this feature is what turns it into a measurement — or overturns it.

Because FEAT-009's router, decomposition, merge checks and question script are shared, the only
variable is the transport. That is what makes the comparison worth anything.

### The structural asymmetry, which is itself the finding

An A2A lane is *send an English sub-question, receive an answer*. Metric resolution, MAQL, filter
choice and chart selection all happen inside the workspace against its own model.

MCP does not have that shape. MCP hands you **tools**, and someone still has to do the analytics
reasoning. So to compare fairly, each workspace's MCP server must be wrapped in a **per-workspace
sub-agent** that takes the sub-question, runs its own tool loop, and returns an answer.

Which means: **to federate over MCP you must build the thing A2A hands you for free.** That is not
an argument to make on a slide; it is a diff that can be shown, and the cost of building it is
measurable in this feature.

### A deliberately minimal tool set

The reference implementation exposes 17 tools per workspace. This uses **four**, chosen so the
model can answer analytical questions and do nothing else:

| tool | why it is in |
|---|---|
| `get_workspace_info` | cheap orientation — name, description |
| `list_workspace_metrics` | find metric ids, `rsql_filter` for keyword search |
| `list_workspace_attributes` | find label ids to slice by |
| `execute_query` | the data retrieval. Everything else exists to feed it |

Nothing for authoring visualizations, alerts, automations or memory. `get_maql_guide` is out
because `execute_query` takes an AAC query block rather than MAQL.

This is MCP given its **best shot**, deliberately. A restricted, well-chosen tool set is what a
thoughtful integrator would build, and a comparison against a bloated one proves nothing. If MCP
still loses at four tools, that finding is worth something.

### Where the cost actually lands

Restricting the tool set does not remove the catalog problem — it **relocates** it, and this is the
thing the measurement has to capture.

`execute_query`'s own description says it: *"Get IDs first with `list_workspace_metrics` or
`list_workspace_attributes`."* So the model cannot answer anything without first pulling metric and
attribute lists into context. `globalmart-customer` has 186 metrics. Filtered by keyword it is less,
but it is paid **per question**, and per exploration round-trip, rather than once per request.

And it costs turns. A single sub-question becomes `list_metrics` → `list_attributes` →
`execute_query`, at least three sequential model turns before an answer exists — each with its own
latency. A2A does all of that inside the workspace, in one call, against a model that already knows
the semantic layer.

So the honest hypothesis this feature tests is not "MCP has too many tools." It is: **MCP moves
semantic reasoning out of the workspace and into the orchestrator's context window, and charges for
it in round-trips and repeated catalog payloads.**

### Two MCP variants, because the naive one is what a customer tries first

**Flat.** All four workspaces' tools in one context: 4 × 4 = **16 tools**, against A2A's four agent
cards. The host model routes by picking tools. Comfortably below the ~30-tool point where tool
choice is thought to degrade, so this variant is viable rather than a strawman — the interesting
failure is not tool selection but knowing which workspace's catalog to consult, and conflating
metrics that share a name across models.

**Nested.** One sub-agent per workspace, each holding only its own four tools, with the top-level
orchestrator sending sub-questions exactly as it does over A2A. The fair comparison, and the honest
cost of MCP federation.

## Appetite

`m` — 1–2 weeks, and only after FEAT-009 works. `simulate_ui.py` already runs a tool loop against
one workspace with a system prompt, so the loop exists; the work is the sub-agent wrapper, the two
variants, and the measurement harness.

## Acceptance Criteria

1. The same **question and conversation script** FEAT-009 uses runs unchanged over both MCP
   variants. A question added to the script is automatically part of every comparison.
2. The orchestrator's **router, decomposition, merge checks and merge prompt are literally the
   same code** as the A2A path. Only the `Lane` implementation differs. A comparison whose
   orchestrator differs measures the wrong thing.
3. The tool set is **four tools per workspace** — `get_workspace_info`,
   `list_workspace_metrics`, `list_workspace_attributes`, `execute_query` — and adding a fifth is
   a deliberate decision recorded with a reason, not a drift.
4. **Flat** is implemented: every workspace's tools in one context (16), host model routes by tool
   choice.
5. **Nested** is implemented: one sub-agent per workspace holding only that workspace's four tools,
   receiving the sub-question and returning an answer.
6. Per question and per variant, the harness records: **tokens in and out**, wall-clock latency,
   which workspaces were reached, whether the answer was correct, and cost.
7. **Round-trips are counted per lane**, not just latency — the number of model turns between
   sub-question and answer. This is where MCP's cost concentrates once the tool set is small, and
   it is invisible in a wall-clock figure alone.
8. **Catalog payload is measured**: how many tokens of metric and attribute listing enter context
   per question. A2A sends a sentence; MCP sends whatever `list_workspace_metrics` returns, every
   time.
9. Metric-disambiguation errors are counted, not just noted — cases where the model picked a metric
   from the wrong workspace, or conflated two metrics sharing a name across models.
10. A written **recommendation** with the numbers behind it, stating plainly where each protocol
    wins and under what conditions the recommendation would flip.
11. The comparison is **reproducible**: one command runs all three paths over the script and emits
    the report.

## Scope

- An MCP `Lane` implementation satisfying the same interface as the A2A one.
- The per-workspace sub-agent: system prompt, that workspace's tools, its own loop, returns an
  answer plus the lane shape FEAT-009's merge checks expect.
- The flat variant, as a deliberate contrast rather than a strawman.
- A comparison harness: run the script across A2A, MCP-flat and MCP-nested; emit a table into
  `reports/`.
- The written recommendation.

## Out of Scope

- Improving GoodData's MCP server. If it has gaps, they go in the gap list; fixing them is gdc-nas
  work.
- Making MCP lose. The flat variant is the naive integration, not a rigged one — it gets the same
  care and the same prompts, and if it wins that is the finding.
- A production MCP orchestrator. This measures; it does not ship.
- Any protocol beyond these two.

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The comparison is unfair without anyone noticing, because the MCP path got less prompt care | Medium | High | Shared orchestrator code (AC 2) removes most of it; for the rest, have someone who wants MCP to win read the prompts before the numbers are published |
| Results vary run to run, so the comparison is noise | High | Medium | Run the script several times per variant and report spread, not a single figure. A protocol recommendation resting on one run of ten questions is not evidence |
| The minimal tool set is so restricted that MCP cannot answer questions A2A can, and the comparison measures the restriction rather than the protocol | Medium | High | Four tools were chosen to cover discovery and retrieval, which is what the questions need. If a question fails for want of a fifth tool, add it and record why — that is a finding about what MCP federation actually requires, not a defeat |
| The sub-agent becomes a second orchestrator with its own quality problems | Medium | Medium | Keep it deliberately thin: one workspace, one sub-question, its own tools, no routing decisions of its own |
| Effort here delays the Infobip demo | Medium | High | Strictly after FEAT-009. This informs the recommendation; the demo does not depend on it |

## Dependencies

- **Depends on:** feat-009 — the router, decomposition, merge checks, question script and `Lane`
  interface all come from it. Starting this first would mean building them twice.
- **Enables:** nothing in the tree. Its output is a recommendation and a set of numbers.

## Related Research

- `demos/mcp_ui/simulate_ui.py` in the broadridge repo: 1,520 lines, `AnthropicBedrock` or
  `Anthropic`, system prompt loaded from `docs/agent-config/mcp-config.md`, and a tool loop over
  17 GoodData tools. The loop to reuse already exists; this feature takes four of the tools.
- `execute_query`'s own description states the dependency: *"Get IDs first with
  list_workspace_metrics or list_workspace_attributes."* That sentence is the round-trip cost, in
  the vendor's own words.
- Metric counts per demo workspace: customer 186, store-ops 63, marketing 49, ecommerce 11. The
  first is what a `list_workspace_metrics` call can put into context.
- `src/gd_debug/mcp_client.py` (921 lines) provides `GoodDataMCPClient`.
- gdc-nas pins `mcp==1.29.1` alongside `a2a-sdk[http-server]>=0.3.0,<1.0`. Both protocols are
  first-class server-side; neither is a side project.
- Prior analysis put MCP tool-choice degradation at roughly 30 tools in one context. Four
  workspaces at four tools each is 16, so tool selection is not expected to be the failure mode.
- Claude does not speak A2A — its extension surface is MCP. Any "show it inside Claude" path needs
  the MCP route regardless of which protocol we recommend, which is a reason to build this beyond
  the comparison.

## Open Questions

- **Is Portal Copilot's tool interface MCP, A2A, or its own?** Unconfirmed. If it speaks MCP
  natively then MCP is the integration surface whatever the comparison says, and this feature
  decides only *how* to shape the MCP side rather than whether to use it.
- Should the sub-agent use a smaller, cheaper model than the orchestrator? It does bounded work in
  one workspace. Realistic for cost, but another variable in a comparison that already has enough.
- How many runs make the numbers credible — three, ten? Enough to show spread without the harness
  becoming the project.
- Does the flat variant need its own tool-name disambiguation (prefixing by workspace), or is
  watching it fail without one the more useful result?
- Should `list_workspace_metrics` be called with a keyword filter derived from the sub-question, or
  unfiltered? Filtered is what a careful integrator does and reduces the payload; unfiltered is
  what happens when nobody tunes it. Measuring both would isolate how much of MCP's cost is
  inherent and how much is integration quality.

## Outcome — 2026-10-24

Judged against the code in `src/gd_agents/` (commits b5ea749, f4a0fb2, 6478c57, 4b07c7c,
637ff6d, eed232f) and one paired live measurement taken today for this review.

**Built:** the nested MCP arm. There is one `MCPLane` per workspace, sitting behind the same
`Lane` interface as A2A, and `--protocol a2a|mcp` is available on `ask`, `serve` and `rehearse`.
**Not built:** the flat arm, the comparison harness and report, disambiguation counting and the
written recommendation. The spec's core thesis, that MCP has to rebuild what A2A provides, is
demonstrated and measured on single questions. The protocol *comparison* is not built yet.

| AC | Verdict | Evidence |
|---|---|---|
| 1. Same script over both MCP variants | **Partly met** | `--protocol` on `rehearse`/`route`/`serve` reads `config/questions.yaml` unchanged (`cli.py:287`, `_protocol`). Holds for nested only, because flat does not exist. Test `test_the_protocol_swaps_the_lane_and_nothing_else` (added today). |
| 2. Router, decomposition, checks and merge are the same code | **Met** | `cli.py:149` `_lanes()` is the only branch point. `lane.py` holds the shared interface. Test `test_the_protocol_swaps_the_lane_and_nothing_else`, plus `test_the_shape_comes_from_the_query_the_sub_agent_actually_ran` and `test_rows_become_the_same_artifacts_the_a2a_lane_returns`. |
| 3. Four tools; a fifth only with a recorded reason | **Met** | Five tools in `mcp/client.py:50` `DEFAULT_TOOLS`. `ai_search` is the fifth, with its reason recorded there and in `docs/mcp-findings.md`: about 1.4k tokens against about 70k for unfiltered listing, roughly 52x cheaper. The whitelist is enforced client-side (`test_a_tool_outside_the_set_is_refused`). Drift guard: `test_the_mcp_tool_set_is_the_recorded_five_and_nothing_drifts` (added today). Finding: the endpoint is a 3-tool gateway (`create_visualization`, `search_tools`, `call_tool`), not 17 tools. |
| 4. Flat variant (all tools in one context) | **Not met** | Nothing implements it; `grep flat src/gd_agents` finds only a docstring. |
| 5. Nested variant | **Met** | `mcp/lane.py:120` `MCPLane`: a per-workspace sub-agent with its own system prompt, five tools, up to 16 turns and its own context. Tests: `test_the_sub_agent_resolves_then_queries_then_answers`, `test_running_out_of_turns_is_a_failure_not_an_answer`, `test_a_tool_error_does_not_end_the_loop`, xtab parsing tests. |
| 6. Per question/variant: tokens, latency, workspaces, correctness, cost | **Partly met** | `Answer` carries tokens, latency and workspace, and `ask` prints them (`fanout.py` `summary_lines`). `rehearse` prints routing and latency but not tokens. Nothing records correctness or cost, and nothing writes them to a per-variant table. |
| 7. Round-trips per lane | **Met (data), not reported** | `Answer.round_trips` = model turns (`mcp/lane.py`). It goes into the payload (`run.py:118`) and the `lane_done` event. `test_the_sub_agent_resolves_then_queries_then_answers` asserts 3. It appears in `ask` output but not in `rehearse` output or any report. |
| 8. Catalog payload measured | **Partly met** | Per tool and per workspace by `gd-agents mcp-probe` (`docs/mcp-findings.md`): unfiltered metrics listing about 43k tokens on customer and about 70k across all four. Tool definitions cost about 4k tokens per question (`gd-agents mcp-tools`). Per-question context goes to the event stream only (`MCPClient.chars_in`) and is not recorded per question in a harness. |
| 9. Metric-disambiguation errors counted | **Not met** | Not counted anywhere. Today's run produced one by hand: marketing's sub-agent swapped *Total Campaign Spend* for *Total Spend (Campaign ROI)* for the ranking and said so. |
| 10. Written recommendation | **Not met** | No recommendation document. `docs/a2a-federation.md` and `docs/a2a-gaps.md` record the asymmetry and two MCP product asks (date-filter examples, union validation errors), but not a verdict or the conditions that would flip it. |
| 11. One reproducible command, three paths, report | **Not met** | There is no compare command and nothing writes to `reports/`. `rehearse --protocol X` must be run once per arm and read by eye. |

**Recorded measurements**

- 2026-09-23, `single-customer`: A2A ~24 s, 1 round trip, 0 lane tokens. MCP 46 s, 8 turns,
  118,058 in / 1,387 out. Same answer.
- 2026-09-23, a marketing single question: MCP 11 turns, 10 tool calls, 45.6 s, 180,983 in. Its
  rows matched A2A's exactly.
- 2026-10-24, `pair-campaign-satisfaction`, one `ask` per protocol, live:

  | | A2A | MCP (nested) |
  |---|---:|---:|
  | routed to | marketing, customer | marketing, customer |
  | lane round trips | 2 | 19 |
  | lane tokens in / out | 0 / 0 (the workspace pays) | 357,140 / 5,470 |
  | slowest lane | 61.8 s | 64.8 s |
  | total | 78.1 s | 70.8 s |
  | merged? | yes, on month | **no**: `time_window_match` failed |
  | correct? | no: lanes returned charts with no readable numbers (provenance 0/1) | no merged answer; lanes correct individually (marketing Q3 by month: 13,615.75 / 15,772.28 / 10,173.54) |

  On this question the cost is in tokens and turns, not latency: wall-clock was close. The MCP
  arm's refusal was a false negative. Marketing reported an absolute window
  (2026-07-01..2026-09-30) and customer a relative one (-1..-1 QUARTER). Both mean last
  quarter, but the check cannot equate them. One run each, so this is not evidence of spread.

**Recommendation:** do not close. The minimum left is AC 4, 9, 10 and 11:

- a flat variant;
- a `compare` command that runs the script over a2a / mcp-flat / mcp-nested and writes
  tokens, turns, catalog tokens, latency, routing, correctness and cost to `reports/`;
- a disambiguation count;
- the written recommendation.

Alternatively, re-scope AC 4/9/11 out explicitly and close on nested plus a written
recommendation built from the numbers above.

## Outcome — 2026-10-24 (final)

This builds on the review above. Added: the flat arm (`src/gd_agents/mcp/flat.py`, `ask
--protocol mcp-flat`), the comparison harness (`src/gd_agents/compare.py`, `gd-agents compare`,
with prices in `config/prices.yaml`), a time-window check that compares resolved dates
rather than spellings (`checks.normalise_window`), `Answer.catalog_chars`, a
`profile --token-env` that defaults to the registry's variable, and the recommendation in
`docs/mcp-vs-a2a.md`. One live comparison was run: `compare --limit 3` over
`single-ecommerce`, `single-marketing` and `pair-campaign-satisfaction`, with the report at
`reports/protocol-compare-2026-10-24.{md,json}`.

| AC | Verdict | Evidence |
|---|---|---|
| 1. Same script over both MCP variants | **Met for questions; conversations nested only** | `compare` reads `config/questions.yaml` unchanged and runs every single-turn question over a2a/mcp/mcp-flat. Conversations run over a2a and mcp via `rehearse --protocol`. Flat has no session, so multi-turn conversations are not run over it. |
| 2. Same router, decomposition, checks, merge | **Met for nested; flat differs where its definition requires** | Nested: unchanged, with `_lanes()` as the only branch. Flat routes by tool choice, so it **cannot** call `plan()`. Its host writes the answer, so there is no `merge()` model call. It shares `tool_loop`, `build_answer`, `run_checks`, `check_provenance`, `separate_answers` and `Run`, and the table in `mcp/flat.py` lists each stage. Test: `test_flat_routes_by_tool_choice_and_shares_the_loop_and_the_gates`, which asserts function identity. |
| 3. Four tools; a fifth recorded | **Met** (unchanged) | Five tools, `ai_search` with its reason. Flat uses the same `DEFAULT_TOOLS`, namespaced per workspace. |
| 4. Flat variant | **Met** | `FlatHost`: 5 tools × N workspaces in one context (20 here), named `<workspace>__<tool>`. Routing is whichever workspace the host runs `execute_query` on. Tests: `test_flat_holds_every_workspaces_tools_namespaced`, `test_flat_cannot_assert_a_number_no_workspace_returned`. |
| 5. Nested variant | **Met** (unchanged) | The loop is now `mcp.lane.tool_loop`, shared with flat, and the existing nested tests pass unchanged. |
| 6. Tokens, latency, workspaces, correctness, cost per question/variant | **Met, correctness unscored** | The `compare` table has all of these columns. Cost comes from `config/prices.yaml` and is `—` for an unlisted model. Correctness is recorded as `unscored` because the script carries routing expectations, not answers. Routing exactness against `expect` is reported separately (3/3 in all three arms). |
| 7. Round trips per lane | **Met** | `round_trips` per row, and `lane_round_trips` per workspace in the JSON. Live: A2A 5, nested 53, flat 38. |
| 8. Catalogue payload per question | **Met** | `Answer.catalog_chars` holds the output of the discovery tools, per lane. Live: 0 / 37,130 / 29,508 tokens. |
| 9. Disambiguation counted | **Met, with a heuristic recorded as such** | Three counts: `substituted` (prose admits another metric), `off_named` (returned metric titles do not include the one the router named, an upper bound) and `cross_workspace` (flat used a metric id discovered in another workspace). Tests: `test_a_row_carries_every_measured_column`, `test_flat_counts_a_metric_borrowed_from_another_workspace`. Live: one real event, A2A on `single-marketing`, missed by the first regex and corrected by hand in the report. The regex is now widened, with a test. |
| 10. Written recommendation | **Met** | `docs/mcp-vs-a2a.md`, linked from `docs/mcp-findings.md`: A2A to federate, MCP nested when the host speaks only MCP or needs rows, flat not beyond one or two workspaces. It states the flip conditions: A2A values that stay unreadable, a workspace-side bill, prompt caching on the MCP loop, and more workspaces. |
| 11. One reproducible command | **Met** | `gd-agents compare [--limit N] [--only ids] [--variants ...]` writes the md and json reports. |

**Time-window false negative (from the review above):** fixed. Relative and absolute windows
are resolved to calendar dates before comparison. Test:
`test_last_quarter_written_two_ways_is_one_window`, the exact pair seen live. It was not
re-exercised live, because the backend failed first.

**What the live run does not show:** answer quality. The org's query backend returned
`SQLException: Connection Error` on every `execute_query` during the run, and A2A returned
charts without values. Cost, turns and catalogue payload are real. Correctness and spread
are not established. The spec's own risk ("one run of ten questions is not evidence")
stands, and this was one run of three.

**Recommendation:** close as built, with two follow-ups outside this spec:

- re-run `compare` once the backend is healthy, ideally with expected answers added to the
  script;
- measure prompt caching on the MCP loop, the most likely thing to change the cost verdict.
