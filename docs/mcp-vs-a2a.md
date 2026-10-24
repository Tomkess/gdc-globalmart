# MCP or A2A for multi-workspace questions: the recommendation

FEAT-014, AC 10. Written from measured numbers. The sources are
`reports/protocol-compare-2026-10-24.{md,json}` (`gd-agents compare`, 3 questions × 3 arms)
and the earlier single-question measurements recorded in the FEAT-014 spec. The sample is
small, so read the conclusions as *orders of magnitude*, not percentages.

## The numbers

Three questions from `config/questions.yaml` (`single-ecommerce`, `single-marketing`,
`pair-campaign-satisfaction`), one run each, model `claude-opus-4-7`, same router, checks
and merge code in every arm.

| | A2A | MCP nested | MCP flat |
|---|---:|---:|---:|
| caller tokens in (3 questions) | **11,132** | 1,265,693 | 1,768,667 |
| caller tokens out | 1,430 | 15,345 | 11,332 |
| est. caller cost | **$0.09** | $6.71 | $9.13 |
| model round trips | **5** | 53 | 38 |
| catalogue tokens into context | **0** | 37,130 | 29,508 |
| median latency | 82 s | 64 s | **45 s** |
| two-workspace question latency | **82 s** | 122 s | 145 s |
| routing exact (vs script) | 3/3 | 3/3 | 3/3 |
| disambiguation events | 1 (hand-corrected) | 0 | 0 |

Earlier paired runs, from the spec, agree: `single-customer` was A2A ~24 s with 1 round trip
against MCP 46 s with 8 turns and 118k tokens. `pair-campaign-satisfaction` on 2026-10-24
was A2A 78 s with 2 round trips against MCP 71 s with 19 turns and 357k tokens.

**Caveat on this run:** the org's query backend failed throughout (`SQLException: Connection
Error` on `execute_query`), so no arm produced a checkable number. Cost, turns and
catalogue payload are real. Answer quality is **unscored**, both because of that and because
the script carries no expected answers. The MCP arms' token counts include retries against
the failing backend, which inflates them somewhat. The earlier healthy-backend runs above
show the same ~30–100× token gap, so the conclusion does not rest on the failure.

The failure was ours, not GoodData's. The full error was `Can't open a connection to same
database file with a different configuration than existing connections`: the demo domains used
a legacy data source and `globalmart_preprod`/`_master` used gdcloud's, both on the same
MotherDuck database. The domains were moved onto gdcloud's data source and the legacy one was
deleted, the same day. Afterwards MCP answered again (3,109 online orders last month).

## The recommendation

**Use A2A to federate across GoodData workspaces.** The caller pays roughly 1% of the tokens
MCP needs: about 4k against 150k–980k per question. It makes one round trip per workspace
against 9–31, and puts no catalogue in its context. The semantic reasoning (which metric,
which date dataset, which filter shape) stays inside the workspace, against the model that
knows the semantic layer. Over MCP the caller rebuilds that reasoning in its own context, and
pays for it on every question. Latency is a wash on single questions and favours A2A on the
two-workspace one.

**Use MCP nested when the host can only speak MCP, or when the caller needs the rows.**
Claude's extension surface is MCP, and Portal Copilot's may be. MCP nested is then the right
*shape*: one sub-agent per workspace, a restricted tool set, `ai_search` before any listing.
It gives every number as a row the caller can check, which A2A did not do in either live run
(charts with no readable values). Budget about 100× the caller-side tokens and 10–15 model
turns per workspace.

**Do not use MCP flat for more than one or two workspaces.** It was the most expensive arm,
at about 1.4× nested's tokens. Every turn carries all twenty tools and the whole shared
history. There is no router, so there are no sub-questions to audit, and the arm is the only
one that *can* use one workspace's metric id in another. That did not happen in three
questions (`cross_workspace` = 0). It is cheaper in wall-clock only because one loop does
less fan-out. It is what a customer gets by connecting four MCP servers to one assistant,
and it is the configuration to steer them away from.

## What would flip it

- **A2A keeps returning charts without values.** In both live runs A2A's numeric
  provenance was empty: the merge had nothing to check. If that persists, A2A's cheapness
  is the cheapness of an answer that cannot be verified, and MCP nested is the better
  default wherever a number is the deliverable.
- **The workspace-side bill counts.** A2A's figure is what the *caller* pays. The workspace
  agent's own model spend is invisible to us and was not measured. If GoodData bills that
  spend to the customer at a similar rate, the gap narrows to whatever the workspace agent's
  efficiency is. It does not invert: the MCP sub-agent is doing the same work with less
  knowledge.
- **Prompt caching on the MCP loop.** Not used here. The MCP loops resend identical tool
  definitions and a growing history every turn, which is the case caching was made for.
  It could plausibly cut MCP's input cost several-fold, which would be enough to close most
  of the cost gap but not the turn count. This is the next measurement to take.
- **More workspaces per question.** Flat's context grows with every workspace connected,
  and nested's cost grows with every workspace asked. A2A's grows by one sentence per
  workspace.

## Reproduce

```bash
set -a; . ./.env; set +a
uv run gd-agents compare --limit 3                    # the spend cap: N questions × 3 arms
uv run gd-agents compare --only pair-campaign-satisfaction --variants a2a,mcp
```

Column definitions, including exactly what counts as a disambiguation event, are in the
docstring of `src/gd_agents/compare.py`.
