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
- feat-014
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

One prompt, a registry of **four** GoodData workspaces with four different data models, and one
merged answer that says which workspace each part came from. AIS-55, for Infobip.

Four rather than the ticket's two, because Infobip's case *is* four (a fifth is being discussed)
and "done when" asks us to say what works at four to five. With four registered, that answer is
evidence instead of extrapolation — and the router decides how many to call, so a question needing
two calls two. A demo that always calls everything has not demonstrated routing at all.

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

### The shape

```
system prompt  ──  the four workspaces, each with a condensed description:
                   what it covers, its key metrics, its vocabulary — at LLM
                   level, not the raw catalog

question  ──▶  LLM call #1  ──▶  route + plan
                                 · which workspaces are relevant, and why
                                 · what to ask each one  ← decomposition

               fan out  ──▶  A2A per chosen workspace, in parallel
                             each lane returns an answer *and its shape*

               answers  ──▶  merge checks  ──▶  LLM call #2
                                                combine where safe, attribute,
                                                shape for the frontend
```

**Decomposition is the part that makes this federation.** The orchestrator does not forward the
raw question to every chosen workspace — it writes a different sub-question per workspace, because
each holds only part of the answer in its own vocabulary:

> *"Did the campaigns we spent most on actually move customer satisfaction?"*
> → marketing: *"top campaigns by spend last quarter"*
> → customer: *"NPS trend by month last quarter"*

Neither workspace is asked the original question, because neither can answer it.

### Not fabricating the connection

Two answers computed against different models are not automatically combinable, and a merge that
invents a link is worse than one that declines. **The hard rule: the merge may not compute.** It
compares, ranks, sequences and narrates; every number in its output must appear verbatim in a lane
result. No sums across workspaces, no ratios spanning two sources. "Cost per NPS point" — marketing
spend divided by a customer-workspace score — is the archetype: both numbers real, the quotient
meaningless, because the grains and populations differ.

That rule is checkable rather than aspirational, which is why it is the one that is enforced in
code rather than asked for in a prompt.

Around it sits a **registry of merge checks**, structured so that adding a ninth is a data entry
and not a prompt rewrite. Each check has an id, what it guards against, and whether code or the
model decides it; each produces the same verdict shape so the report is uniform:

| id | guards against | decided by |
|---|---|---|
| `lane_completeness` | synthesising as if a failed lane had answered | code |
| `time_window_match` | comparing last quarter against last month | code |
| `shared_dimension` | claiming a link with no common key at the same grain | code |
| `filter_parity` | one lane filtered to a region, the other not | code |
| `unit_compatibility` | mixing currencies or units | code |
| `numeric_provenance` | any number in the output that no lane produced | code |
| `metric_identity` | assuming the same word means the same metric across models | model |
| `population_parity` | comparing "customers who bought" against "all customers" | model |

The first six are deterministic and gate the merge. The last two are judgement and are posed to the
model as structured verdicts rather than left implicit. The set is deliberately open — these eight
are a starting point, not a claim of completeness.

**When the checks say no:** present both answers separately, attributed, with the one-line reason.
The ticket forbids side-by-side as the *default*, but an honest "these do not combine, here is each"
beats a fabricated link — especially for a customer whose own aggregate workspace already failed
them.

### Why routing is the hard version here

Four different products mean four different semantic models. The orchestrator cannot assume a
shared vocabulary, cannot rely on a metric meaning the same thing in two places, and has nothing
to join on. Every routing decision is made from the question against workspace *descriptions*,
and every merge happens in language over answers that were computed independently.

This is also where A2A earns its place over MCP: metric disambiguation, MAQL, filters and chart
choice all happen inside each workspace against its own model. The orchestrator never sees a
catalog. Infobip is explicitly fine with either protocol — the choice is ours, and Jan Brandejs'
preliminary view after talking to Chris is that A2A fits better.

### The four demo workspaces

GlobalMart's domain workspaces have genuinely different pruned LDMs, so they model the shape rather
than simulate it. **Zero fact-table overlap across all six pairs**, while sharing date and customer
dimensions — federation, with nothing to join on.

| Workspace | Facts | Metrics | Vocabulary | Infobip analogue |
|---|---|---|---|---|
| `globalmart-customer` | 6 | 186 | NPS, feedback, loyalty points, tier change | **Conversation** — interaction detail |
| `globalmart-marketing` | 5 | 49 | spend, impressions, email sends, paid clicks | **Moments** — campaigns |
| `globalmart-store-ops` | 5 | 63 | footfall, staffing hours, energy, maintenance | **Answers** — service delivery |
| `globalmart-ecommerce` | 1 | 11 | order count, average order value | **Overview** — broad but thin |

The last row is the one that earns its place. `globalmart-ecommerce` covers a broad topic with one
fact table and eleven metrics — which is precisely Overview's character: nominally spans everything,
lacks the detail. So the demo can reproduce **the failure Infobip actually hit**. Ask something
Overview appears to cover, watch it answer shallowly, and have the orchestrator reach the detailed
workspaces instead. That is their pain demonstrated rather than described, and it is a stronger
beat than any amount of explaining why one aggregate workspace is not enough.

A question like *"did the campaigns we spent most on last quarter actually move customer
satisfaction?"* needs marketing and customer and neither alone. A question about order volumes
should route to ecommerce alone — which is what proves the router is deciding.

## Appetite

`m` — 1–2 weeks. The client, auth, SSE plumbing and artifact renderers already work in
`simulate_a2a.py`. The work is de-globalising the workspace, the registry, route/fan-out/merge,
multiplexing the stream, and keeping attribution intact through the merge.

## Acceptance Criteria

1. A prompt entered in the front end returns **one merged answer** built from two or more workspace
   agents over A2A — not answers side by side — demoable without a walkthrough of the code.
2. The workspaces consulted are **chosen from the question**. Calling all four every time fails
   this as surely as hard-coding would. The router must return a subset — one workspace when the
   question needs one — which is what proves the decision is real.
3. Every part of the merged answer is **attributed to the workspace it came from**, and attribution
   survives the merge structurally rather than by asking the model to be tidy.
4. The registry holds **four workspaces with four different LDMs**, matching Infobip's shape. A pair
   sharing a model does not test what needs testing, and two workspaces cannot answer the
   four-to-five question with evidence.
5. A lane that fails or times out degrades the answer and says so. It never fails the whole query.
6. Each lane's status, latency and artifacts are visible while it runs, so a viewer can see that
   the calls happened in parallel and against separate workspaces.
7. The registry is data, not code: adding a workspace is a config entry with a description, and no
   orchestrator change.
8. Each lane returns its **shape** alongside its answer — sub-question, grain, time window,
   filters, whether data came back — and the merge sees it.
9. The merge **may not compute**. Every number in the merged output appears verbatim in a lane
   result, asserted programmatically rather than requested in a prompt.
10. Merge checks are a **registry**: adding one is a data entry, not a change to the merge code.
    The eight named in this spec are the starting set.
11. When the checks refuse, the answer presents each lane separately, attributed, with the reason —
    it never invents a connection.
12. A **question and conversation script** is committed, covering the cases listed in Scope, and is
    used for both the demo and the routing measurement.
13. **The gap list is written**, covering at minimum: agent discovery (findable or wired by hand),
   auth (one token or one per agent, and what happens when the caller can see only one workspace),
   routing reliability across different models, attribution of merged results, and measured latency
   at four agents with a stated projection for five.
14. Latency is **measured at four lanes**, per lane and end to end, over the script. The
    five-workspace answer is then a short extrapolation from four rather than a guess from two.
15. One scripted beat shows the **Overview problem**: a question the thin workspace nominally
    covers, answered shallowly by it and properly once the detailed workspaces are reached.
16. The condensed workspace descriptions are **generated by the profiler**, not hand-written, and
    whatever the profiler had to reach for is recorded in the gap list.
17. **Enrich works**: a failed lane can be retried alone and the answer re-synthesised over the
    union, without re-running the lanes that succeeded.
18. Runnable by someone who is not its author, from a README, including whatever access is needed.

## Scope

- A workspace registry — id, description, endpoint — loaded from config.
- A **profiler** that builds each workspace's condensed description by querying the workspace
  itself — agent card, metric titles, AI memory — rather than by hand.
- `plan(question, registry)`: one LLM call returning the chosen workspaces, the sub-question for
  each, and its reasoning.
- `fanout`: parallel A2A calls with a per-lane timeout and per-lane failure isolation. Each lane
  returns its answer **and its shape**: sub-question asked, grain, time window, filters applied,
  and whether it returned data at all.
- A **merge-check registry** — the eight above, extensible by adding an entry — with the
  deterministic ones gating and the judgement ones posed as structured verdicts.
- `merge(question, results, verdicts)`: one LLM call producing a single attributed answer, or
  separate attributed answers with a stated reason when the checks refuse.
- **Enrich**: per-lane results held in session state by conversation, so a failed or missing lane
  can be retried alone and re-synthesised over the union — reusing that lane's `context_id` rather
  than starting cold.
- **A question and conversation script** (see below), which is both the demo runbook and the
  measurement input.
- De-globalising `_workspace` in `simulate_a2a.py` so several workspaces can be called concurrently
  at all — the load-bearing refactor everything else depends on.
- Multiplexed SSE so up to four lanes stream independently into one page, with a routing banner
  and per-lane panes.
- The gap list, written as the work happens rather than reconstructed afterwards.
- A latency measurement pass, run over the script.

### The question and conversation script

A committed file, not something improvised on the day. It serves three purposes at once: it is the
demo runbook, it is the routing-reliability measurement input, and it is the regression set when a
prompt changes.

Each entry carries the question, the workspaces a human says it should reach, and what it exists to
show. Conversations carry an ordered list of turns.

It must cover, at minimum:

- a question reaching **one** workspace — the proof that routing selects rather than broadcasts
- a question needing **two**, where neither can answer alone
- a question needing **three or four**, for the latency measurement
- a pair that is **not safely mergeable**, so the checks are seen refusing
- the **Overview beat**: something the thin workspace nominally covers, answered shallowly by it
  and properly once the detailed workspaces are reached
- a lane that **fails or times out**, and the answer degrading honestly
- a **follow-up that re-routes** to a workspace not used in the first turn
- a **follow-up that reuses** an engaged lane's `context_id`
- an **enrich** case: a lane fails, is retried alone, and the answer is re-synthesised

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
| Latency at four lanes is untenable for a live demo | Medium | High | A2A calls have run 20–80s in prior work and fan-out costs the slowest lane, so four could mean a 90s wait on stage. Measure early (AC 9); if it is bad, that is a finding worth having — and the router calling two of four for most questions is the honest mitigation, not a trick |
| Four live workspaces is more demo surface to keep working | Medium | Medium | They already exist and are published; the cost is keeping their data current, which is FEAT-013's job anyway |
| The demo runs on data whose dates stop in 2024, so "last quarter" returns nothing | High without feat-013 | High | FEAT-013 moves the window to the present. Until it lands, avoid relative-date questions or the demo dies on the first prompt |
| Artifact rendering assumes one workspace | Medium | Medium | Two lanes return their own visualization DataParts; the renderer needs a source label per artifact |
| Effort goes into the orchestrator rather than the gap list | Medium | High | The gap list is what product and the customer actually receive. Write it continuously; it is AC 8, not a closing task |

## Dependencies

- **Depends on:** nothing hard. In practice feat-013 makes the demo safe — current data, and
  dashboards whose numbers are worth showing.
- **Enables:** feat-010, which swaps the execution runtime for LangGraph and is explicitly
  droppable, and feat-014, which reuses everything here over MCP to make the protocol comparison a
  measurement rather than an opinion.

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
- **Answered 2026-09-21:** the MCP comparison is worth building, and is now FEAT-014 — the same
  orchestrator over MCP, flat and nested, measured on this feature's question script. That makes
  the `Lane` interface load-bearing rather than tidy: FEAT-014 reuses the router, decomposition,
  merge checks and script unchanged, so only the transport varies.
- Is a fifth workspace worth registering, since Infobip are already discussing one? Cheap to add
  if the registry is data, and it would make the five-workspace answer measured rather than
  extrapolated.
- Does the `globalmart-ecommerce`-as-Overview beat survive contact with a real question, or is its
  thinness so obvious that the moment lands as contrived?
