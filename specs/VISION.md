# Vision

GlobalMart is a broad, fully reproducible retail dataset — schema, data, semantic layer and
analytical content — defined as code in the GoodData Python SDK rather than as exported
declarative JSON, so that any domain can be rebuilt from source on demand. It is built once and
reused for many purposes: LLM and agent evaluation, local and hosted inference benchmarking,
A2A and MCP protocol testing, demos and general analytics experimentation. Every layer — data
generation, warehouse load, datasource wiring, LDM, metrics, visualizations, dashboards and AI
context — is versioned, parameterized by target host/org/datasource, and idempotently
publishable into any domain the owner controls, giving full control over data flows and no
dependency on a live workspace as the source of truth.

---

**How to use this file:**
- Keep it to one paragraph — if it needs more, it's a strategy doc, not a vision.
- Read it before creating a new goal (`/goal new`).
- Run `/vision` to update it via guided conversation.
- Every goal, feature, and decision should be traceable back to this.
