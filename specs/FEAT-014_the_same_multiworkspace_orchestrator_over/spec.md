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

MCP does not have that shape. MCP hands you **tools** — 17 of them per workspace in the existing
implementation — and someone still has to do the analytics reasoning. So to compare fairly, each
workspace's MCP server must be wrapped in a **per-workspace sub-agent** that takes the
sub-question, runs its own tool loop, and returns an answer.

Which means: **to federate over MCP you must build the thing A2A hands you for free.** That is not
an argument to make on a slide; it is a diff that can be shown, and the cost of building it is
measurable in this feature.

### Two MCP variants, because the naive one is what a customer tries first

**Flat.** All four workspaces' tools in one context: 17 × 4 = **68 tools**, against A2A's four
agent cards. The host model routes by picking tools. This is what someone integrating GoodData into
a tool-picking orchestrator would do on day one, and prior analysis put the breakdown point for
tool-choice quality at roughly 30 tools — so the interesting question is not whether it degrades
but how.

**Nested.** One sub-agent per workspace, each holding only its own 17 tools, with the top-level
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
3. **Flat** is implemented: every workspace's tools in one context, host model routes by tool
   choice.
4. **Nested** is implemented: one sub-agent per workspace holding only that workspace's tools,
   receiving the sub-question and returning an answer.
5. Per question and per variant, the harness records: **tokens in and out**, wall-clock latency,
   which workspaces were reached, whether the answer was correct, and cost.
6. **Token cost is reported explicitly**, because it is the number that grows with workspace count
   and lands on the customer's inference bill. A2A sends a sentence; MCP sends catalogs.
7. Metric-disambiguation errors are counted, not just noted — cases where the model picked a metric
   from the wrong workspace, or conflated two metrics sharing a name across models.
8. A written **recommendation** with the numbers behind it, stating plainly where each protocol
   wins and under what conditions the recommendation would flip.
9. The comparison is **reproducible**: one command runs all three paths over the script and emits
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
| 68 tools exceeds a context or request limit and flat cannot run at all | Medium | Low | That is itself a publishable result — record the limit and where it was hit rather than trimming the tool set to make it fit |
| The sub-agent becomes a second orchestrator with its own quality problems | Medium | Medium | Keep it deliberately thin: one workspace, one sub-question, its own tools, no routing decisions of its own |
| Effort here delays the Infobip demo | Medium | High | Strictly after FEAT-009. This informs the recommendation; the demo does not depend on it |

## Dependencies

- **Depends on:** feat-009 — the router, decomposition, merge checks, question script and `Lane`
  interface all come from it. Starting this first would mean building them twice.
- **Enables:** nothing in the tree. Its output is a recommendation and a set of numbers.

## Related Research

- `demos/mcp_ui/simulate_ui.py` in the broadridge repo: 1,520 lines, `AnthropicBedrock` or
  `Anthropic`, system prompt loaded from `docs/agent-config/mcp-config.md`, and a tool loop over
  17 GoodData tools — `get_workspace_info`, `list_workspace_metrics`, `execute_query`,
  `create_visualization`, `get_maql_guide` and the rest. The loop to reuse already exists.
- `src/gd_debug/mcp_client.py` (921 lines) provides `GoodDataMCPClient`.
- gdc-nas pins `mcp==1.29.1` alongside `a2a-sdk[http-server]>=0.3.0,<1.0`. Both protocols are
  first-class server-side; neither is a side project.
- Prior analysis put MCP tool-choice degradation at roughly 30 tools in one context. Four
  workspaces is 68.
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
