---
abandoned_at: null
abandoned_reason: null
appetite: m
blocked_at: null
blocked_by: null
confidence: medium
created: '2026-09-20'
cycle: null
depends_on: []
enables:
- feat-010
goal: goal-02
id: feat-009
name: 'A2A multi-workspace orchestrator: extend simulate_a2a.py with a workspace registry,
  question-driven routing, parallel fan-out and one merged answer attributed to its
  source workspaces'
sources: []
status: draft
tags: []
updated: '2026-09-21'
---

## Summary

One prompt, two GoodData workspaces with different data models, one merged answer that says which
workspace each part came from. AIS-55, for Infobip.

The orchestrator we build is a **stand-in for theirs**, not a product. That framing is the whole
point and it changed on 2026-09-21.

### What the account actually looks like

Confirmed by Dominik via Pavel, recorded on the ticket 2026-09-21:

- **One workspace per product, per Infobip end-customer**: Conversation, Answers, Moments,
  Overview. Four products, therefore **four different data models** — not four children of one
  parent sharing an LDM. A fifth is already being discussed.
- **Overview is their own "one workspace that sees everything", and it is not sufficient.** It is
  data-limited, built for customer-journey analysis, missing the detailed conversation data and
  metrics. They have already tried aggregating into one workspace; that is the thing that failed.
  Offering it back to them would show we had not read the account.
- **Their orchestrator already exists.** Portal Copilot sits over ~10 internal tools and picks one
  per task, with plans to expose it externally. GoodData is meant to fill the analytics slot.

So this is **federation** — query each workspace, then synthesise — and the question is not whether
an orchestrator can be built. It is whether GoodData is a good tool inside one somebody else owns.

That makes the **gap list half the deliverable**, not an afterthought. The demo is evidence; the
list of what an orchestrator needs from us is what goes to product and to the customer.

### Why routing is the hard version here

Four different products mean four different semantic models. The orchestrator cannot assume a
shared vocabulary, cannot rely on a metric meaning the same thing in two places, and has nothing
to join on. Every routing decision is made from the question against workspace *descriptions*,
and every merge happens in language over answers that were computed independently.

This is also where A2A earns its place over MCP: metric disambiguation, MAQL, filters and chart
choice all happen inside each workspace against its own model. The orchestrator never sees a
catalog. Infobip is explicitly fine with either protocol — the choice is ours, and Jan Brandejs'
preliminary view after talking to Chris is that A2A fits better.

### The demo pair

GlobalMart's domain workspaces have genuinely different pruned LDMs, so they model the shape
rather than simulate it.

| Workspace | Datasets | Metrics | Vocabulary |
|---|---|---|---|
| `globalmart-marketing` | 20 | 49 | Total Spend, Impressions, Email Sends, Paid Clicks |
| `globalmart-customer` | 24 | 186 | NPS Score, Feedback Count, Loyalty Points, Tier Change |

Zero fact-table overlap, shared date and customer dimensions, genuinely divergent vocabulary. A
question like *"did the campaigns we spent most on last quarter actually move customer
satisfaction?"* needs both and can be answered by neither alone. `globalmart-ecommerce` was
considered and rejected: one fact table and eleven metrics is too thin to pass as a product.

## Appetite

`m` — 1–2 weeks. The client, auth, SSE plumbing and artifact renderers already work in
`simulate_a2a.py`. The work is de-globalising the workspace, the registry, route/fan-out/merge,
multiplexing the stream, and keeping attribution intact through the merge.

## Acceptance Criteria

1. A prompt entered in the front end returns **one merged answer** built from two workspace agents
   over A2A — not two answers side by side — demoable without a walkthrough of the code.
2. The workspaces consulted are **chosen from the question**. Hard-coding both calls fails this.
   The router must be able to return one workspace when the question only needs one, which is what
   proves the decision is real.
3. Every part of the merged answer is **attributed to the workspace it came from**, and attribution
   survives the merge structurally rather than by asking the model to be tidy.
4. The two workspaces have **different LDMs**. A pair sharing a model does not test what Infobip
   needs tested.
5. A lane that fails or times out degrades the answer and says so. It never fails the whole query.
6. Each lane's status, latency and artifacts are visible while it runs, so a viewer can see that
   the calls happened in parallel and against separate workspaces.
7. The registry is data, not code: adding a workspace is a config entry with a description, and no
   orchestrator change.
8. **The gap list is written**, covering at minimum: agent discovery (findable or wired by hand),
   auth (one token or one per agent, and what happens when the caller can see only one workspace),
   routing reliability across different models, attribution of merged results, and measured latency
   at two agents with a stated projection for four and five.
9. Latency is **measured, not estimated** — per lane and end to end, across a set of questions, so
   the four-to-five-workspace answer is evidence rather than a guess.
10. Runnable by someone who is not its author, from a README, including whatever access is needed.

## Scope

- A workspace registry — id, description, endpoint — loaded from config.
- `route(question, registry)`: one LLM call returning the chosen workspaces and its reasoning.
- `fanout`: parallel A2A calls with a per-lane timeout and per-lane failure isolation.
- `merge(question, results)`: one LLM call producing a single attributed answer.
- De-globalising `_workspace` in `simulate_a2a.py` so two workspaces can be called concurrently at
  all — the load-bearing refactor everything else depends on.
- Multiplexed SSE so lanes stream independently into one page, with a routing banner and per-lane
  panes.
- The gap list, written as the work happens rather than reconstructed afterwards.
- A latency measurement pass.

## Out of Scope

- **Cross-workspace joins.** This is federation. Anything that needs rows from two models in one
  computation is a different feature and probably a different product.
- **Suggesting an aggregate workspace.** Infobip built Overview and it was insufficient. Raising it
  is worse than useless.
- Tenancy and per-user identity. The caller's identity decides which workspaces exist for them;
  that is a permission boundary, not a routing decision. Real auth is a production concern and
  belongs in the gap list, not the demo.
- Workspace data filters and parent/child hierarchy — FEAT-012, parked 2026-09-21 precisely because
  Infobip's workspaces are independent products.
- Productising the orchestrator. It stands in for Portal Copilot. Its job is to be deleted.
- The LangGraph runtime — FEAT-010, which depends on this and is droppable.

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Routing picks the wrong workspaces on questions that span different vocabularies | Medium | High | This is the thing being tested, not a defect to hide. Measure it across a question set and report the failures in the gap list — a known hit rate is a better deliverable than a demo that only works on one rehearsed prompt |
| The merge launders provenance and the answer cannot be traced | Medium | High | Keep each lane's answer verbatim and addressable; merge references them rather than absorbing them (AC 3) |
| Latency at two lanes is fine and at five is not | Medium | High | Measure rather than assume (AC 9). A2A calls have run 20–80s in prior work, and fan-out costs the slowest lane. If five is untenable, that is a finding worth having early |
| The demo runs on data whose dates stop in 2024, so "last quarter" returns nothing | High without feat-013 | High | FEAT-013 moves the window to the present. Until it lands, avoid relative-date questions or the demo dies on the first prompt |
| Artifact rendering assumes one workspace | Medium | Medium | Two lanes return their own visualization DataParts; the renderer needs a source label per artifact |
| Effort goes into the orchestrator rather than the gap list | Medium | High | The gap list is what product and the customer actually receive. Write it continuously; it is AC 8, not a closing task |

## Dependencies

- **Depends on:** nothing hard. In practice feat-013 makes the demo safe — current data, and
  dashboards whose numbers are worth showing.
- **Enables:** feat-010, which swaps the execution runtime for LangGraph and is explicitly
  droppable.

## Related Research

- Starting point: `Tomkess/broadridge-a2a-mcp-debugging`, now all on `main` — the
  `ptom/a2a-optimization` branch no longer exists. `demos/a2a_orchestrator/simulate_a2a.py` is 857
  lines, of which roughly 600 are an embedded HTML page; module-level `_host`, `_token`,
  `_workspace` around line 630 are the refactor point.
- `src/gd_debug/a2a_client.py` provides `send_message`, `stream_message_events` and artifact
  extraction. `demos/mcp_ui/simulate_ui.py` is the MCP path, available as a contrast pane.
- gdc-nas serves A2A from `microservices/gen-ai/app/presentation/a2a/` using `a2a-sdk`, with
  `AgentCapabilities(streaming=True)`, no push notifications and no extended card. Task states in
  use: `completed`, `failed`, `input_required`. Artifacts are GoodData-specific DataParts:
  `visualization`, `visualization-data`, `key-driver-analysis`, `what-if-analysis`,
  `search-results`, `alert-proposal`.
- No cross-workspace agent discovery endpoint exists: list workspaces, then fetch each agent, then
  its card. This is the product ask most directly relevant to a portal that adds A2A connections.
- Claude does not speak A2A; its extension surface is MCP. Any "show it in Claude" path needs an
  MCP front door.

## Open Questions

- **Does Infobip use parent→child hierarchy underneath, per end-customer beneath each product?**
  Recorded as unconfirmed on the ticket. It changes how an orchestrator enumerates and authorises
  workspaces, and the answer may differ per product line. Worth asking Dominik.
- Is Portal Copilot's tool interface MCP, A2A, or its own? "Adding an A2A connection" implies A2A,
  but if the portal speaks MCP natively then the MCP front door is the integration surface and the
  protocol recommendation changes.
- How many questions make a credible routing measurement — ten, thirty? Too few and the hit rate is
  noise; too many and the set becomes the work.
- Should the MCP contrast pane be built at all now that Infobip is protocol-agnostic? It stops
  being persuasion and becomes internal evidence for our own recommendation, which may be worth
  less than the time it costs.
- Does the demo need a third workspace to make the four-to-five story credible, or does two plus a
  measured latency curve carry it?
