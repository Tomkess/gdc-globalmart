# AIS-55: Multi-Workspace A2A Orchestration

Session handoff document. Written 2026-09-20. Demo target: Thursday 2026-09-24.

Load this into a fresh session to resume the work without re-deriving anything.

---

## 1. The ticket

**AIS-55** — presales demo for **Infobip**.

Their objection: *GoodData's MCP is workspace-scoped, and our deployment spans 4
unconnected workspaces per customer.*

The ticket does **not** ask to fix MCP. It asks for a demo of A2A-based
orchestration: one GoodData A2A agent per workspace, an orchestrator in front
that routes questions to the right subset and merges answers.

Starting point: `demos/a2a_orchestrator/simulate_a2a.py` in this repo. It is
deliberately positioned as a stand-in for *Infobip's own orchestrator*, not as a
test harness.

The ticket also asks that friction points found while building be written up as
a concrete product ask.

Deployment context: Infobip runs GoodData **CN** (self-managed), and has on the
order of **hundreds of clients**.

---

## 2. The mental model — the grid

This is the core idea. Everything else follows from it.

Infobip is not "N workspaces". It is a grid:

```
                client_1   client_2   client_3   …   client_300
  SMS            ws_a1       ws_a2      ws_a3          ws_a300
  Email          ws_b1       ws_b2      ws_b3          ws_b300
  Voice          ws_c1       ws_c2      ws_c3          ws_c300
  Support        ws_d1       ws_d2      ws_d3          ws_d300
```

- **4 rows** = business domains. Fixed, defined once by Infobip.
- **~300 columns** = their clients. Grows continuously.
- **~1200 workspaces** total.

### The one rule

> The orchestrator moves **down a column**. Never across a row.

A user at `client_2` asks a question. The orchestrator considers exactly
`ws_a2, ws_b2, ws_c2, ws_d2`. Four. That is the entire world for that request.

It never sees `client_1`'s workspaces. It never sees all 1200.
**"Hundreds of workspaces at once" never occurs.**

### Why this collapses the scaling problem

| Axis | Size | Who crosses it |
|---|---|---|
| Rows (domains) | 4 | the orchestrator, every request |
| Columns (clients) | ~300 | **nobody** — hard isolation boundary |

The two axes never multiply. The routing prompt always holds 4 descriptions —
at 300 clients, at 3000 clients.

**Consequence: no vector index, no embedding registry, no RAG.** Semantic
retrieval only earns its cost past ~50 candidates in one decision, and that
number is structurally capped at 4 here. This is not a demo shortcut; it is the
production design.

### Where the registry comes from

**Row descriptions — authored once, 4 total, shared by every client:**

```yaml
SMS:     "SMS traffic: messages sent, delivery rate, cost per message"
Email:   "Email campaigns: opens, clicks, bounces, deliverability"
Voice:   "Voice calls: volume, connect rate, duration"
Support: "Tickets: volume, resolution time, CSAT"
```

**Cell IDs — looked up, never authored:**

```
client_2 → {SMS: ws_a2, Email: ws_b2, Voice: ws_c2, Support: ws_d2}
```

Infobip already owns this mapping — they provision the workspaces.

**Onboarding client 301:** provision 4 workspaces from existing templates. Write
zero descriptions. Change zero orchestrator code. That is the O(1) claim.

### Request flow

```
1. alice@client_2 asks "which channel had worst delivery last month?"
2. identity      → tenant = client_2      ← from her session, NEVER the request body
3. registry      → 4 row descriptions + client_2's 4 workspace ids
4. route         → [SMS, Email, WhatsApp]        (one LLM call)
5. fan-out       → 3 parallel A2A calls
6. merge         → one answer                     (one LLM call)
```

Step 2 is the security boundary. If tenant resolution accepts anything the user
can set, one client reads another's data. Routing decisions themselves leak
which workspaces exist.

The orchestrator is **stateless**. One deployment serves all clients. Scale
horizontally.

---

## 3. Why A2A, not MCP — the argument that makes the demo land

Three ways to answer a cross-workspace question:

**REST/AFM (Infobip's status quo)** — they write code per question. Metric IDs,
AFM payloads, joins, all in their codebase. Every new question is a release.
GoodData's semantic model gets re-implemented in Infobip's code.

**MCP × 4 workspaces** — the orchestrator's LLM gets tools from four servers. It
must hold four catalogs in context and do the analytics reasoning itself: which
metric means "revenue" here, what date grain, which filter. Workspace A calls it
`gross_sales`, workspace B calls it `net_revenue`. The orchestrator has to know.

**A2A × 4 agents** — the orchestrator sends the *English question*, gets back an
*answer plus artifacts*. Metric disambiguation, MAQL, filters, chart choice all
happen inside GoodData, against each workspace's own semantic model, AI memory
and permissions. The orchestrator never sees a catalog.

> **MCP delegates execution. A2A delegates reasoning.**

That sentence is the pitch. Everything in the demo should exist to prove it.

### Supporting beats (all cheap, all real)

- **Token economics.** A2A payload = one sentence. MCP payload = catalog per
  workspace. Put a live token counter on both panes. That number is Infobip's
  inference bill and it does not grow with workspace count.
- **Governance.** Flip `isHidden` on a metric mid-demo. The A2A agent stops using
  it; the orchestrator never knew it existed. With MCP the orchestrator holds
  credentials to everything. *Blast radius of an orchestrator bug is bounded by
  GoodData's permissions.*
- **Independent evolution.** Add an AI Memory disambiguation rule in one
  workspace. Answer improves. Zero orchestrator changes, zero redeploy.
- **Ownership.** The workspace owner — who knows the data — improves answer
  quality by editing workspace metadata. Not Infobip's platform team.

---

## 4. The critical prior failure mode

An early plan built the *mechanism* (route/fan-out/merge) with no *contrast*. It
showed a thing working. Nobody could tell whether it was hard or whether A2A
earned anything — Infobip would assume they could write it in a week, and they'd
be right.

**A demo of AIS-55 without the MCP-vs-A2A contrast is weak.** The contrast is
the deliverable; the router is a boring 200-line detail shown for five seconds.

---

## 5. Solution catalogue

Nine approaches evaluated. Effort assumes the state of this repo as of
2026-09-20.

### 5.1 Extend `simulate_a2a.py` — baseline

- **Stack**: Python stdlib, `requests`, Anthropic SDK. No new dependency.
- **Architecture**: one process. `workspaces.yaml` → LLM route call →
  `ThreadPoolExecutor` fan-out over `send_message()` → LLM merge → existing SSE UI.
- **Program it**: refactor the global `_workspace` (`simulate_a2a.py:630`) into a
  per-call parameter. Add `route()`, `fanout()`, `merge()`. ~200 lines.
- **Deploy**: `python3 simulate_a2a.py`, laptop, port 8900.
- **Demo**: routing banner at ~2s with chosen workspaces + reason; lanes render
  as they land; merged answer on top.
- **Benefits**: lowest risk. Auth, SSE, artifact renderers already work. Zero
  deploy, zero new concepts under time pressure.
- **Effort**: 1.5 days. **Thursday: yes, with slack.**

### 5.2 LangGraph orchestrator

- **Stack**: `langgraph`, `langchain-core`, existing `a2a_client.py`.
- **Architecture**: `route` node → `Send()` fan-out → N parallel `ask` nodes →
  reducer fan-in → `merge` node. Checkpointer holds the per-workspace
  `context_id` map across turns.
- **Program it**: one new file `orchestrator.py`, ~40 lines of graph plus the
  three functions. `simulate_a2a.py` imports the compiled app and streams
  `astream(stream_mode="updates")`.
- **Deploy**: same as 5.1 — it is a library in-process.
- **Demo**: same UI, plus a LangSmith trace on a second screen showing the graph
  execute — route fires, lanes run concurrently with individual latencies, merge
  fans in.
- **Benefits**: `Send` is purpose-built for runtime-decided fan-out. Checkpointer
  gives multi-turn `context_id` free. `interrupt()` handles A2A `input-required`
  on one lane while others keep running. Trace is a genuine demo asset.
- **Costs**: new dependency; gdc-nas has no LangGraph and will not adopt one, so
  this layer is throwaway if AIS-55 productizes.
- **Effort**: 2 days. **Thursday: yes, only if 5.1 lands first.**

### 5.3 MCP aggregator — no orchestrator at all

- **Stack**: `FastMCP`, `a2a_client.py`. Host LLM = Claude.
- **Architecture**: one MCP server exposing five tools (`ask_sms`, `ask_email`,
  …). Each wraps one A2A endpoint. **Claude does routing and merging** via
  native tool choice and parallel tool calls.
- **Program it**: ~60 lines. Five `@mcp.tool()` decorators. Tool docstrings
  become the routing descriptions.
- **Deploy**: stdio — `claude mcp add gooddata -- uv run python mcp_server.py`.
  Zero hosting.
- **Demo**: inside Claude itself. Claude visibly calls three of five tools in
  parallel and writes the synthesis.
- **Benefits**: smallest thing that satisfies AIS-55. No router, no merger, no UI
  to write. Routing quality free from a frontier model. Runs in the customer's
  own assistant.
- **Costs**: no control over routing, cannot show the decision explicitly; no
  custom artifact rendering; breaks down past ~30 tools.
- **Effort**: 0.5 day. **Thursday: yes. Use as the second pane.**

### 5.4 AWS Strands Agents SDK

- **Stack**: `strands-agents`, Bedrock (Claude Sonnet 4.6). First-class A2A and MCP.
- **Architecture**: Strands agent with five A2A-backed tools, model-driven loop
  rather than explicit graph.
- **Program it**: agent definition + tool wrappers, ~80 lines. Less glue than
  LangGraph because A2A is built in.
- **Deploy**: purpose-built for AgentCore Runtime (`agentcore launch`); also a
  plain container on App Runner or ECS.
- **Demo**: same fan-out; AgentCore observability gives per-tool CloudWatch traces.
- **Benefits**: AWS-native, matching where GoodData already sits (Bedrock, S3).
  Cleanest path to AgentCore Identity/Memory. No Google dependency.
- **Costs**: less explicit fan-out control than `Send`; new framework this week.
- **Effort**: 2.5 days. **Thursday: risky.** Good week-2 path.

### 5.5 Bedrock AgentCore Runtime (hosting layer, framework-agnostic)

- **Stack**: AgentCore Runtime + Identity + Memory + Gateway. Hosts Strands,
  LangGraph, ADK, CrewAI.
- **Architecture**: the orchestrator from 5.2 or 5.4, hosted managed. Identity
  handles inbound OAuth; Memory handles session state; Gateway can expose the
  whole thing as MCP.
- **Program it**: unchanged orchestrator plus an AgentCore entrypoint wrapper.
- **Deploy**: `agentcore configure` + `agentcore launch`. Invoked via
  `InvokeAgentRuntime` (SigV4) or through Gateway.
- **Demo**: same as the wrapped framework, from a hosted endpoint.
- **Benefits**: solves per-user identity, session persistence and MCP front door
  in one place. Supports A2A and stateful MCP servers (since Mar 2026).
  Strongest *production* answer in AWS.
- **Costs**: `InvokeAgentRuntime` is a SigV4 API, not a plain OAuth HTTPS URL —
  **verify** whether Identity's inbound auth satisfies Claude's connector
  requirement or whether API Gateway is needed in front. AWS lock-in.
- **Effort**: +2 days on an orchestrator. **Thursday: no.**

### 5.6 AWS Step Functions fan-out

- **Stack**: Step Functions (Distributed Map), Lambda per lane, Bedrock for
  route and merge. No agent framework.
- **Architecture**: `Route` (Lambda→Bedrock) → `Map` over chosen workspaces, one
  Lambda each → `Merge` (Lambda→Bedrock).
- **Program it**: ASL JSON plus three small Lambdas.
- **Deploy**: CDK or SAM. Fully serverless.
- **Demo**: the Step Functions console **is** the visual — live execution graph,
  parallel branches, per-branch timing. Best orchestration visual of any option,
  and free.
- **Benefits**: durable execution, automatic retries, per-branch error handling,
  native observability. Enterprise audiences recognise it instantly.
- **Costs**: SSE streaming through Step Functions is awkward — per-lane live
  streaming mostly goes away. Slower iteration than editing a Python file.
- **Effort**: 2.5 days. **Thursday: no.** Good "production shape" slide.

### 5.7 AgentCore Gateway → MCP, host-side routing

- **Stack**: AgentCore Gateway, Lambda/OpenAPI targets, any MCP host.
- **Architecture**: Gateway converts the A2A endpoints into MCP tools with
  managed auth. The host model routes. Managed, multi-tenant version of 5.3.
- **Program it**: Gateway target config plus a thin (or one parameterised) Lambda.
- **Deploy**: Gateway is managed; Lambdas via SAM.
- **Demo**: in Claude or cowork, hosted, with real auth.
- **Benefits**: production version of 5.3. Managed OAuth, per-user identity, no
  orchestrator to run. Matches Infobip embedding GoodData in their own assistant.
- **Costs**: same routing opacity as 5.3; AWS lock-in; new config surface.
- **Effort**: 2 days. **Thursday: no.**

### 5.8 GoodData-native parent-workspace agent — the product answer

- **Stack**: gdc-nas `gen-ai`, `a2a-sdk`, declarative agents API
  (`getAgentsLayout` / `setAgentsLayout`).
- **Architecture**: no customer orchestrator. A parent workspace exposes one
  agent card; gen-ai fans out to child workspace agents internally and merges.
- **Program it**: new routing skill in gen-ai's skill registry, using the
  existing `ConversationService` and workspace hierarchy. Registry derived from
  declarative agent configs, which already carry per-workspace name, description,
  instructions.
- **Deploy**: existing helm charts (`helm-charts/gooddata-cn/templates/gen-ai`),
  feature-flagged per org.
- **Demo**: one endpoint, one question, N workspaces answered. Nothing for the
  customer to build — that is the pitch.
- **Benefits**: deletes the integration. Removes the objection rather than
  working around it. The only option that is a product rather than a pattern.
- **Costs**: weeks, needs product buy-in.
- **Effort**: weeks. **Thursday: no.** This is the closing slide.

### 5.9 Google ADK — evaluated and rejected

- **Would be**: coordinator with five `RemoteA2aAgent` sub-agents, or one
  `BaseToolset` returning them dynamically.
- **Rejected because**: ADK's hierarchy is fixed at init and runtime agent
  creation is explicitly discouraged (breaks state management, introspection,
  observability) — see adk-python discussion #4346. The
  `BaseToolset.get_tools(readonly_context)` escape hatch exists but fights the
  framework. Non-Gemini models go through LiteLLM while GoodData runs
  Bedrock/Anthropic/OpenAI/Azure. Adds a Google dependency to a GoodData artifact
  for zero customer-visible benefit.
- **Keep as**: a ~50-line adapter in the client package so a Google-shop prospect
  can plug the router into their ADK graph. Not a build path.

### Selection

| # | Effort | Thursday | Best at |
|---|---|---|---|
| 5.1 Extend simulate_a2a | 1.5d | yes | risk floor |
| 5.3 MCP aggregator | 0.5d | yes | contrast pane, smallest proof |
| 5.2 LangGraph | 2d | if 5.1 lands | trace visual, multi-turn |
| 5.4 Strands | 2.5d | risky | AWS-native week 2 |
| 5.6 Step Functions | 2.5d | no | production visual |
| 5.5 AgentCore Runtime | +2d | no | production identity |
| 5.7 AgentCore Gateway | 2d | no | customer-embedded end state |
| 5.8 GoodData-native | weeks | no | the roadmap ask |

**Recommended for Thursday: 5.1 + 5.3 together.**

5.1 as the main pane — you control the routing decision, show it explicitly,
render artifacts properly. 5.3 in half a day as a second pane inside Claude:
same workspaces, zero orchestrator code, host model routes.

The pairing gives a contrast readable without a diagram: *here it is with an
orchestrator you control, here it is with no orchestrator at all — both work,
because each workspace agent owns its own semantics.*

---

## 6. Day plan to Thursday

**Monday**
1. *First hour, before code:* confirm the grid is real (see Open Questions) and
   that four workspaces with genuinely divergent metric naming exist and are
   reachable. This is the only true blocker.
2. `workspaces.yaml` + loader.
3. `route(question) -> [(ws_id, reason)]` — one Anthropic call returning
   `{"workspaces": [...], "reasoning": "..."}`.
4. Refactor the global `_workspace` into a per-call parameter.

**Tuesday**
5. `ThreadPoolExecutor(max_workers=5)` fan-out. Per-lane timeout ~90s. A failed
   or timed-out lane returns a marker — **never fail the whole query**.
6. `merge(question, results) -> str` — one Anthropic call.
7. UI: routing banner, collapsible lane per workspace with status/latency/
   artifacts, merged answer on top. Token counter on both panes.
8. Point `simulate_ui.py` (MCP path) at the same workspaces so the MCP pane is a
   real run, not a strawman. **Do not rig it** — let it struggle honestly.
9. **5pm checkpoint**: if LangGraph (5.2) is being attempted and is fighting,
   delete `orchestrator.py` and keep the ThreadPoolExecutor version. Do not let
   it eat Wednesday.

**Wednesday**
10. Rehearse the *contrast*, not the feature. Three beats: wrong-metric moment,
    add-a-workspace-live, flip-`isHidden`.
11. Tenant switch: same UI, same code, different column, correct answers.
12. Cache a good run to disk; add `--replay`. Network insurance.

**Thursday morning** — dry run on the real projector and network. Nothing new.

### Demo narrative

Demo **one column**. Four workspaces, one client. Route, fan out, merge.

Then the line that does the work:

> "That's client_2. Client_1 through client_300 are the same four descriptions
> and a different id lookup. Nothing in this code changes. Adding a client is a
> provisioning step, not an engineering step."

Then, live: **switch tenant.** Two seconds of clicking proves the scaling story.

Close with the productization slide:

```
Thursday          →  Production            →  Roadmap
YAML registry        declarative agents       native parent-agent routing
one token            per-user identity        unchanged
laptop               Infobip's cluster        GoodData
                     gooddata-a2a-client      one card, no orchestrator
```

### Cut list — say no on sight

Vector index. ADK. Cloud hosting. OAuth. Claude connector. Cross-workspace data
joins. Agent registry service. Persistent sessions. Anything in gdc-nas.

---

## 7. Production path (beyond the demo)

**Registry must come from GoodData, not from Infobip's YAML.** The descriptions
have a home already: the declarative agents API carries per-workspace name,
description, instructions and skills. Infobip provisions workspaces from
templates; agent identity rides along in the same step. The registry becomes a
*read*, not an authored artifact — zero drift, and the description that drives
routing is owned by whoever owns the workspace.

**Auth.** End user authenticates to Infobip → exchanged for a GoodData identity
per user → passed on every lane call → GoodData enforces workspace permissions
server-side. The orchestrator must never hold a token that sees more than the
caller. The registry is therefore per-user, not just per-tenant; cache per
session.

**Multi-turn.** Each lane has its own `context_id`. The orchestrator holds
`conversation_id → {ws: ctx}`. Follow-ups re-route (a second question may need
different workspaces) and reuse `context_id` only for lanes already engaged; a
newly engaged lane lacks earlier turns, so enough context must be replayed into
the prompt.

**What GoodData ships** — a sequence, not alternatives:
1. *Reference implementation* (this repo, cleaned up). Fast, zero stickiness,
   their fork diverges in a month.
2. *Supported client package* `gooddata-a2a-client` — registry reader, router,
   fan-out, artifact renderers. **Right near-term answer.** Infobip keeps their
   runtime, auth and UI; GoodData owns the layer that knows GoodData semantics.
   Every new artifact type lands in their product on a version bump.
3. *Platform feature* (5.8). The endgame — deletes the integration entirely.

**CN changes make this easier, not harder.** All workspaces live in one
installation Infobip operates; A2A endpoints are internal hostnames (no public
internet, no third-party OAuth); the orchestrator is another service in their
cluster; identity is already theirs. Everything about AgentCore, App Runner and
Claude connectors belongs to the Broadridge/cloud thread, not Infobip.

---

## 8. Ecosystem facts (stop re-deriving these)

**Three distinct things:**

| Thing | What | Owner |
|---|---|---|
| A2A protocol | wire spec — agent card, JSON-RPC `message/send`/`message/stream`, Task lifecycle, artifacts | Linux Foundation since Jun 2025 (Google donated). TSC: AWS, Cisco, Google, IBM, Microsoft, Salesforce, SAP, ServiceNow |
| `a2a-sdk` | reference Python implementation, server + client | a2aproject, LF |
| Google ADK | agent-building framework; speaks A2A as one transport | Google |

**gdc-nas uses `a2a-sdk`, not ADK.** `microservices/gen-ai/pyproject.toml:54` —
`a2a-sdk[http-server]>=0.3.0,<1.0`. The "Google A2A SDK" docstring in
`app/presentation/a2a/app.py:3` is stale naming.

**gdc-nas has no LangGraph and no LangChain agents.** Only
`langchain-text-splitters` for chunking, in one file
(`app/infrastructure/services/text_splitter/document_text_splitter.py:6`).
gen-ai hand-rolls its agent loop: own skill registry, `ConversationService`, own
LLM adapter over OpenAI/Anthropic/Bedrock/Azure. Protocol SDKs yes
(`a2a-sdk`, `mcp==1.29.1`), orchestration frameworks no. **A LangGraph
orchestrator sets no precedent and would be rewritten if AIS-55 productizes.**

**Server A2A surface today** (`microservices/gen-ai/app/presentation/a2a/`):
- Agent card built per-request; workspace-scoped URL + dynamic skills gated by
  feature flags (`app.py:83-104`)
- `AgentCapabilities(streaming=True)` — **no** push notifications, **no**
  extended card (`app.py:156`)
- Task states in use: `completed`, `failed`, `input_required` (`executor.py:283`)
- Artifacts are GoodData-specific `DataPart` types (`artifact_mapping.py`):
  `visualization`, `visualization-data`, `key-driver-analysis`,
  `what-if-analysis`, `search-results`, `alert-proposal`

**Claude does not speak A2A.** Claude's extension surface is MCP — custom
connectors, connector directory, Claude Code servers. Any "show it in Claude"
path needs an MCP front door.

**No cross-workspace agent discovery endpoint.** Pattern must be: list
workspaces → per workspace `GET /api/v1/ai/workspaces/{ws}/agents` → then the
A2A card endpoint. This is a product ask.

---

## 9. Open questions — resolve Monday

1. **Is the grid real?** Are Infobip's 4 workspaces per client genuinely the same
   4 domains for every client (grid holds, everything above is true), or does
   each client get a bespoke set (row descriptions no longer shared, per-client
   authoring returns)? The ticket's "4 unconnected workspaces per customer"
   implies a uniform grid, but this single fact is load-bearing for the entire
   scaling argument.
2. **Four demo workspaces with divergent metric naming** — do they exist, are
   they reachable? Note `ai_dev_si` has `earlyAccess="experimental-a2a-server"`;
   the default broadridge workspace returns 400 on A2A.
3. **CN A2A availability.** Kapa found no CN changelog mention of A2A at any
   version. Confirm with engineering, or run the demo on a Cloud tenant with an
   explicit caveat.
4. **AgentCore inbound auth** (only if 5.5/5.7 are pursued): does Identity expose
   OAuth-compatible inbound auth, or is API Gateway required in front of
   `InvokeAgentRuntime`?

---

## 10. Product asks for the ticket write-up

- **Agent card discovery for a workspace hierarchy** — one call returning the
  cards of all child workspaces a user can see. Today it is N card fetches and
  you must already know the N.
- **Per-message reasoning effort** — undocumented whether `message/send` can
  carry it, or whether it is only an Agent Hub default. Without it an
  orchestrator has no per-query speed/depth control. (GDAI-1805)
- **No task cancellation, resubscription or retrieval** on the GoodData side. All
  run state lives in the client; a dropped connection loses the task.
  (`docs/agent-config/a2a-config.md:184`)
- **No push notifications** — long queries must hold a stream.
- **A2A latency** 20–80s budget; org/workspace config dominates (model swap
  40–50%, `isHidden` catalog pruning, AI Memory disambiguation). See
  `docs/findings/a2a-latency.md`.
- **CN parity for A2A**, if confirmed missing.

---

## 11. Key file references

| Path | What |
|---|---|
| `demos/a2a_orchestrator/simulate_a2a.py` | the prototype orchestrator; global `_workspace` at :630 is the refactor point |
| `demos/mcp_ui/simulate_ui.py` | MCP path with Claude picking tools — the contrast pane |
| `src/gd_debug/a2a_client.py` | A2A JSON-RPC client, `send_message()` |
| `src/gd_debug/mcp_client.py` | MCP JSON-RPC client |
| `docs/agent-config/a2a-config.md` | the br-cowork A2A skill config |
| `docs/findings/a2a-latency.md` | every known latency lever, measured |
| gdc-nas `microservices/gen-ai/app/presentation/a2a/` | server side: `app.py`, `executor.py`, `artifact_mapping.py` |
| gdc-nas `helm-charts/gooddata-cn/templates/gen-ai` | deployment path for 5.8 |

---

## 12. Sources

- [A2A Protocol](https://a2a-protocol.org/latest/)
- [Google donates A2A to Linux Foundation](https://developers.googleblog.com/en/google-cloud-donates-a2a-to-linux-foundation/)
- [ADK dynamic agents limitation (#4346)](https://github.com/google/adk-python/discussions/4346)
- [ADK custom tools / BaseToolset](https://google.github.io/adk-docs/tools-custom/)
- [LangGraph graph API](https://docs.langchain.com/oss/python/langgraph/use-graph-api)
- [LangGraph map-reduce with Send](https://deepwiki.com/langchain-ai/langchain-academy/7.1-map-reduce-pattern)
- [Bedrock AgentCore overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
- [AgentCore stateful MCP (Mar 2026)](https://aws.amazon.com/about-aws/whats-new/2026/03/amazon-bedrock-agentcore-runtime-stateful-mcp)
- [Claude custom connectors / remote MCP](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
