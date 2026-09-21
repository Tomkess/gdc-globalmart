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
status: draft
tags: []
updated: '2026-09-21'
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
