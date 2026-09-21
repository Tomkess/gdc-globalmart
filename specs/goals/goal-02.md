---
id: goal-02
name: A2A and MCP demonstrated as implementable over GlobalMart
status: active
created: 2026-09-20
horizon: 1-year
measurable_outcome: A prospect-facing demo, runnable from this repo against GlobalMart workspaces with genuinely different LDMs, answers a question that needs more than one of them over A2A with a single attributed answer — plus a written account of what a third-party orchestrator needs from GoodData and what is missing, concrete enough to hand to product.
---

GoodData's agent surfaces — A2A per workspace, MCP per workspace — are each scoped to a single
workspace, and every customer with more than one workspace hits that boundary immediately. The
standard answer is that an orchestrator composes over them, and customers are already building
those orchestrators: Infobip's Portal Copilot sits over ~10 internal tools and picks one per task,
with GoodData meant to fill the analytics slot. So the question is not whether an orchestrator can
be built. It is whether GoodData is a good tool inside one somebody else owns — and nobody has
checked, because presales has no A2A asset at all. This goal makes GlobalMart the proving ground:
its 12 domain workspaces are the axis an orchestrator actually crosses — each one a pruned slice of
the parent with its own reachable LDM, its own metric vocabulary and its own AI context, so
selecting between them is a genuine semantic routing decision rather than a tenant lookup. That
matches the shape confirmed for Infobip on 2026-09-21: one workspace per product, four different
data models per end-customer, with their own aggregate workspace already tried and found
insufficient. This is federation — query each, then synthesise — not a cross-workspace join. Tenancy
is deliberately out of scope: which tenant a question belongs to comes from the caller's identity,
never from the question, so it is a permission boundary and not something an orchestrator reasons
about. Success is a demo somebody else can run, and a gap list that turns "you could build an
orchestrator" into a supported pattern with a reference implementation behind it.
