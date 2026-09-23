# A2A federation over GlobalMart

One question, several GoodData workspaces with different data models, one attributed answer.
Built for **AIS-55** (Infobip), and reusable beyond it.

This is `src/gd_agents/`. It shares a repository with GlobalMart because GlobalMart is the
proving ground, and it shares no code with it: point it at any GoodData org and it works.

---

## What it is, and what it is not

Infobip runs **one workspace per product per end-customer** — Conversation, Answers, Moments,
Overview — so four products, four different data models, nothing joinable across them. Their
own Overview workspace is an attempt at combining everything and it is *not sufficient*:
data-limited, missing the detailed conversation data. So "merge it into one workspace" is not
an answer available to us.

They also already have an orchestrator: **Portal Copilot**, sitting over ~10 internal tools,
with GoodData meant to fill the analytics slot.

So this is **not** a proposal that they build an orchestrator. It is an attempt to find out
whether GoodData is a good tool inside one somebody else owns. Which makes the gap list —
[`a2a-gaps.md`](a2a-gaps.md) — half the deliverable, and this code the evidence behind it.

The viewer stands where Portal Copilot stands. It exists to make a turn watchable and is
meant to be deleted. **The payload is the interface.**

### Rendering what the agent actually sent

An A2A answer carries two artifacts: a **`visualization`** — the agent's own chart type,
title and query — and a **`visualization-data`** with columns, rows and `formattedRows`,
paired by `visualizationId`. The viewer draws the chart the agent asked for rather than
guessing one from the rows: it already decided this was a *line chart of Average Total NPS
Score by Month*, and re-deriving that here would throw the decision away. Formatted values
are used as sent, so `3,995` does not quietly become `3995` and disagree with the answer text
above it.

Line, area, bar, pie, headline and table are drawn as inline SVG or plain HTML — no charting
library, which is the honest answer to *can a host that is not GoodData's UI render one of
these*. Where a declared type cannot be told the truth about the data it was given — a
scatter with one metric — it falls back to a table **and says so underneath**, because a
silent downgrade reads as the agent having ignored the request.

That rendering is under test: the page's chart functions are executed in node against the
artifact shapes a live agent really returns, so "the charts work" is a claim with a gate
behind it rather than a screenshot.

**Agents answer in markdown, so it is rendered.** Bold, bullets to two levels, inline code
and pipe tables — a lane really did return a six-month series as a markdown table. The
renderer escapes first and then introduces only the tags it owns, because text arriving from
a remote agent is an injection surface. It deliberately takes no `_underscore_` emphasis:
object ids are full of underscores and would turn italic halfway through their own name.

**Object ids are resolved to the labels the same response carried.** The agent writes
`{metric/metric_l1_total_campaign_spend}` into its prose while the data artifact beside it
calls that object *Total Campaign Spend*. The mapping is positional and stated by the agent —
`view_by` against the attribute columns, `metrics` against the metric columns — so this
resolves a name the agent already gave rather than inventing one. Done in the lane, so every
host gets readable prose and not just this page. **An id with no mapping is left exactly as
written**, because a plausible label derived from an identifier would be a guess presented as
a fact; it is on the gap list instead.

## The rows behind the answer

Where the lanes combine, the payload carries a `table`: each lane's own series listed against
the grain the checks agreed on, one column per metric, labelled with the workspace it came
from.

**It is alignment, not a join.** No row of one workspace is matched to a row of another by
any business key. Each lane returned an independent series broken down by the same time
grain, and they are listed against that grain — exactly the claim the merge makes in prose.
Two rules keep it honest: only the chart at the shared grain contributes, so a lane's campaign
ranking stays out of a monthly table; and a period one lane did not cover is **blank, never
zero**, because a zero reads as a measured value of nothing. Values are `formattedRows` as
sent, so the table and the sentence above it show a number the same way.

It is offered only when `combinable` is true. A table of two series asserts they are
comparable, and that is precisely the claim the checks exist to gate.

---

## Run it

```bash
uv sync --extra agents

# credentials: an API token for the org, named per the registry
export GLOBALMART_TOKEN__DEMO_CLOUD=...      # GoodData API token
export ANTHROPIC_API_KEY=...                  # the router and the merge
# or, for Bedrock instead:
# export ANTHROPIC_BEDROCK_MODEL=...

# 1. profile the workspaces — writes config/agents.yaml and the discovery findings
uv run gd-agents profile \
  --host https://petertomko.demo.cloud.gooddata.com \
  --workspaces globalmart-customer,globalmart-marketing,globalmart-store-ops,globalmart-ecommerce \
  --apply

# 2. ask something
uv run gd-agents ask "Did campaign spend and customer satisfaction move together over the last 6 months?"

# 3. or watch it in a browser
uv run gd-agents serve            # http://127.0.0.1:8900
```

Other commands:

| command | what it does |
|---|---|
| `gd-agents registry` | the routing prompt, exactly as the router sees it |
| `gd-agents route` | routing accuracy across the whole question script, **without calling any lane** |
| `gd-agents rehearse` | every scripted conversation, end to end, against the live agents |
| `gd-agents ask --json` | the payload a host would receive |
| `gd-agents ask --inject-failure <workspace>` | force a lane to fail, to show degradation |

Expect **30–120 seconds** for a two-lane question. That is agent-side latency, not
orchestration — see [`a2a-gaps.md`](a2a-gaps.md).

### The three routes, and what each claims

| route | for a host that | returns |
|---|---|---|
| `POST /ask` | has no streaming | the payload, after 30–120s of silence |
| `POST /ask/stream` | can show progress | NDJSON events, the last one being that same payload |
| `POST /reply` | has a human in front of it | the re-merged payload, after answering one lane |

`/ask/stream` exists because a spinner held for ninety seconds reads as a hang, and because
the interesting part is invisible otherwise: the router chose *these* workspaces, gave each a
*different* sub-question, and they returned out of order. Its final event is exactly what
`/ask` would have returned, so streaming adds narration and changes nothing about the result.

`POST /reply {workspace, text}` answers a lane that stopped to ask something — see below. Send
`{"ask_me": true}` with a question to get that behaviour; without it, lanes auto-confirm.

---

## How a turn works

```
system prompt  ──  the four workspaces, each with a condensed description
                   (generated by the profiler, not hand-written)

question  ──▶  plan()   ──▶  route + decompose
                             · which workspaces are relevant, and why
                             · a *different* sub-question for each

               fanout() ──▶  A2A per chosen workspace, concurrently
                             each lane returns an answer *and its shape*

               checks   ──▶  may these be combined at all?

               merge()  ──▶  one attributed answer, or several with a reason
                             then provenance: did it invent a number?
```

**The router is given the conversation, and still plans from scratch.** Those are not the
same thing, and the difference is the whole of multi-turn. Without the conversation a
follow-up cannot be routed at all: measured on 2026-09-22, *"which of them converted best?"*
made the router return an empty plan reasoning "there is no prior context" — correct, and
useless. Nine of thirty-five scripted turns failed that way.

With it, the router knows what "them" refers to and writes a sub-question naming the thing
rather than the pronoun. What it must **not** do is reuse the earlier route: *"and did any of
that show up in customer satisfaction?"* follows a marketing turn and belongs to customer. So
every turn re-plans, knowing the thread. The last four turns are shown, each with a short
excerpt of its reply.

**A turn may legitimately need no workspace.** *"Summarise what we have established so far"*
asks about the conversation, and the router says so by choosing nothing. That used to be an
error; it is now answered from the answers already held — no agent call, about three seconds,
and the same merge runs over them so attribution and provenance still apply. With nothing
held it is still an error, because then the router really did fail.

**Decomposition is what makes this federation.** The orchestrator never forwards the user's
question to a workspace, because no workspace can answer it:

> *"Did the campaigns we spent most on actually move customer satisfaction?"*
> → marketing: *"Rank campaigns by Total Campaign Spend for last quarter, **and also** give
>   Total Campaign Spend by month for the last 6 months"*
> → customer: *"Show Average Total NPS Score by month for the last 6 months"*

**A plan that intends to combine must ask for the same shape.** This is the rule most easily
got wrong, and getting it wrong wastes the whole turn. Measured live: asked for spend *by
campaign, last quarter* against satisfaction *by month, last two quarters* — each a good
sub-question, nothing to join on, and a correct refusal after 46 seconds of fan-out. So
`plan.py` requires the same period in the same words, the breakdown named in `combine_on`
asked of every lane, and — before concluding two answers cannot be combined — that time be
tried, because every workspace measures over time even where nothing else is shared. Where a
ranking is also wanted, *that* workspace is asked for both. One workspace can be asked two
things; two workspaces cannot each be asked a different one.

---

## The rules that hold it together

**The merge may not compute.** It compares, ranks, sequences, narrates and attributes. Every
number in its output must appear verbatim in some lane's result, checked against
`Answer.numbers` *after* the merge rather than requested in the prompt. A merge that invents
a value is rejected and replaced by the separate answers.

Given marketing spend of `11,944.45` and an NPS of `27.04`, *"cost per NPS point was 441.73"*
is caught: both inputs real, the quotient meaningless because the grains and populations
differ. No prompt can be trusted to refuse that; a check can.

**Eight merge checks, in a registry.** Adding a ninth is an entry in `CHECKS`. Five are
decided in code and gate the merge; two are judgement and are posed to the model as
structured verdicts; one runs after.

| check | guards against | decided by |
|---|---|---|
| `lane_completeness` | synthesising as if a failed lane had answered | code |
| `time_window_match` | comparing last quarter against last month | code |
| `shared_dimension` | claiming a link with no common key at the same grain | code |
| `filter_parity` | one lane filtered to a region, the other not | code |
| `unit_compatibility` | mixing currencies or units | code |
| `numeric_provenance` | a number in the output that no lane produced | code, after |
| `metric_identity` | the same word meaning different metrics across models | model |
| `population_parity` | "customers who bought" against "all customers" | model |

The eight are a starting set. Completeness is not claimed.

**When the checks refuse, refusing is the answer.** Each lane is presented separately,
attributed, with the reason. The model is not called at all — asking it then would invite it
to argue around a verdict the code already reached. The ticket forbids side-by-side as the
*default*; an honest "these do not combine" beats a fabricated link, especially for a
customer whose own aggregate workspace already failed them.

**`UNKNOWN` is not `PASS`.** A check cannot pass on an absence it never established, or a
lane that reported no shape would silently licence any combination.

**A shared grain is an overlap, not an equality.** A sub-question can legitimately ask one
workspace for two things, and the agent then returns two charts. A lane holding
`{campaign_id, month}` against one holding `{month}` does share a key. `shared_dimension` and
`time_window_match` pass on a non-empty intersection, name the grain they agreed on, and say
out loud what one lane returned that the other did not — the merge is about to be handed
material the lanes do not both hold, and a reader should know which part of it compares. No
overlap is still a `FAIL`; fewer than two lanes reporting is still `UNKNOWN`.

## What a workspace asks, and who answers it

`input-required` is neither an answer nor a failure, and it is the state a caller is least
likely to model. Asked to rank campaigns by spend, the marketing agent found the metric, found
it had no campaign field, proposed two alternatives and stopped — 37.4s, no human in the lane.

There are exactly two honest things to do with that, and both are implemented:

| mode | what happens | when |
|---|---|---|
| auto-confirm (default) | the lane consents once on the same `contextId` and the answer records that it rested on an assumption | unattended fan-out |
| `ask_me` | the question reaches the caller in `payload.pending`, and `POST /reply` sends the human's words to that one workspace | a host with a person in front of it |

Auto-confirming is the orchestrator **guessing** that "yes" was right. Here it plainly was;
nothing guarantees that in general.

Measured: resuming took **16.3s against the 37.4s** the first turn cost, because the agent
kept the work it had already done. So `input-required` is not doubled latency, it is latency
plus a third — which is what makes asking a human viable. And the reply goes to *one*
workspace: the others already answered, and re-asking them would pay the fan-out again to
change nothing, or worse return different numbers and make the merge a comparison across two
different moments.

---

## What survives a lane failing

**About 2% of turns lose a lane.** Measured across three full rehearsals of the scripted
conversations — 105 live turns — there were two genuine lane failures, plus one lane
abandoned at the fan-out deadline. Three modes observed:

| mode | response |
|---|---|
| `HTTP 502` and other transient 5xx | retried once |
| `input-required` — the agent asks permission mid-task | confirmed once, on the same `contextId` |
| agent state `failed`, no detail | retried once, then reported |

An earlier figure of "roughly half of multi-lane runs" circulated in this repository and was
wrong by more than an order of magnitude. It came from ad-hoc runs during early development,
before the retry and deadline work; the rehearsal numbers replace it.

Per-lane isolation still matters, for a less dramatic reason: a four-lane answer missing one
lane is still an answer with a hole in it, and **every answer has to read correctly with a
lane missing**. At 2% a turn, across four lanes and a five-turn conversation, you should
expect to see it during a demo of any length. The reply is assembled from what returned,
never from what was planned.

`enrich` then re-asks only the lanes whose part is still missing and merges the fresh answers
against the ones already held — one lane instead of four. It reuses the earlier sub-question
verbatim: a reworded retry would be a different query, and comparing it against the kept
answers would be invalid.

---

## The question script

[`config/questions.yaml`](../config/questions.yaml) is three things at once: the demo runbook,
the routing measurement input, and the regression set when a prompt changes. `expect` is a
human judgement, written before the prompts existed.

```bash
uv run gd-agents route            # 20 questions, routing only — no lane called, ~1 minute
uv run gd-agents route --turns    # and every turn of every conversation, in its thread
uv run gd-agents rehearse         # every conversation end to end, against the live agents
```

**Twenty questions and seven conversations of five turns each**, served to the page as
one-click prompts at `GET /questions` so a demo is not typed live and the runbook cannot
drift from the buttons.

The most useful single entry is a negative one: **`within-one-workspace`** — *"did energy use
track footfall across the stores last quarter?"* sounds like two workspaces and is one, because
store operations holds both measures. The correct answer is one lane, and a router that fans
out has demonstrated exactly the habit this exercise exists to avoid.

**The conversations are where the mechanism actually shows.** A single question demonstrates
routing; only a thread shows that the route is recomputed every turn, that each workspace
resumes its own conversation, and that a lost lane is recoverable without re-running the ones
that worked. `rehearse` runs them for real — same session, in order, live agents — which is
what lets the file call them verified rather than hoped for.

Last full rehearsal, 2026-09-23: **35 turns, 0 errored, 34 routed exactly.** Writing them is
what found the router had no conversation, the fan-out deadline bounded nothing, and a
timed-out lane was being retried at full cost — none of which was visible while the scripted
conversations were two turns of self-contained questions.

The two measurements answer different questions and can disagree. `route --turns` carries
each turn's *expected* workspaces as history but no replies, so a follow-up whose referent is
a number is resolved more thinly than in a real thread. Where they differ, believe `rehearse`.

### One shape for every entry

Every entry carries the same keys in the same order, `question` is a folded block on all of
them however short, and `load_script` **refuses an unknown key** rather than ignoring it. A
key the loader drops silently is debris the next reader has to guess about. There is a test
asserting the file uses one form, because this drifted once already.

| key | |
|---|---|
| `id` | required, unique across questions and conversations |
| `kind` | groups the entry; the viewer uses it as a heading |
| `question` | required, always `>-` |
| `expect` | required — the workspaces a competent analyst would consult |
| `shows` | what a reader should watch for |
| `note` | a decision about the entry itself, usually why `expect` changed |
| `inject_failure` | force one lane to fail |
| `enrich` | this turn retries the missing lanes instead of asking anew |
| `reply_to` | this turn answers that workspace's `input-required` question |
| `from_memory` | this turn needs no workspace, so `expect` is empty |

A router returning *fewer* workspaces than expected has missed something; one returning
*more* is broadcasting. Both count as misses and are reported separately, because they are
different problems with different fixes.

Routing can be measured without calling a single lane, which is the main practical argument
for an explicit router over a tool-calling loop: reliability is answerable in a minute for
pennies rather than an hour of real agent calls.

**One entry carries a `note`.** `overview-shallow` originally expected three workspaces and
the router chose two — and the router was right. The expectation was narrowed and the reason
written into the file, because an expectation edited to match a router measures nothing.

---

## Adding a workspace

Nothing in the code. Add it to `--workspaces`, re-run `gd-agents profile --apply`, and review
the diff in `config/agents.yaml`. Descriptions are generated by querying the workspace, which
is deliberate: *whether an orchestrator can discover what a workspace covers* is the first
item on the gap list, and hand-writing four descriptions would answer it by assumption.

The answer, for the record, is that **A2A cannot tell you.** All four workspaces advertise an
identical agent card — same name, same description, same nine skills, which are protocol
capabilities rather than subject matter. The profiler reads `datasets`, `metrics` and
`memoryItems` through the metadata API instead: three calls per workspace outside A2A,
needing credentials beyond what an agent connection carries.

---

## Layout

```
src/gd_agents/
  lane.py                  the one interface both protocols implement
  artifacts.py             reading GoodData DataParts — grains, windows, labels
  transport.py             HTTP and SSE, standard library only
  registry.py              which workspaces exist, and what each covers
  profile.py               builds the descriptions by querying the workspaces
  script.py                loads the question script, scores routing
  a2a/client.py            one workspace over A2A
  mcp/                     empty — FEAT-014
  orchestrator/
    align.py               the lanes' rows, side by side on the shared grain
    plan.py                route + decompose, one model call
    fanout.py              concurrent lanes, isolated failures
    checks.py              the eight merge checks, and provenance
    merge.py               one attributed answer, or several with a reason
    session.py             what a conversation remembers
    events.py              the progress feed — narration, never a source of truth
    run.py                 ask(), respond(), enrich(); Run.payload()
  server/                  the minimal viewer
  cli.py                   gd-agents
```

`lane.py` is load-bearing rather than tidy. **FEAT-014** runs this same router, decomposition
and merge over MCP instead of A2A, and a protocol comparison whose orchestrator differs
between the two arms measures the orchestrator, not the protocol.

The asymmetry underneath is the finding. An A2A lane sends an English sentence and receives an
answer, because the workspace agent resolves metrics, writes MAQL and picks a chart against
its own model — `a2a/client.py` is a JSON-RPC POST and some careful reading. MCP offers
*tools*, so something must still do that reasoning: `gd_agents.mcp` will have to build a
per-workspace sub-agent to stand in the same place. **To federate over MCP you must build what
A2A hands you for free**, and the difference in length between the two modules is the
comparison's most honest single number.
