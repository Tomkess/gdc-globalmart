# Org-level state the org repo must adopt

Org-level objects belong to the separate org repo (ADR 011); this repo never releases them. Until
that repo exists, changes made by hand on a live org are recorded here, so its first snapshot
keeps them instead of reverting them.

## usecases-ai (`w2r-kigdm6`) — 2026-10-24

| Object | Before | After | Why |
|---|---|---|---|
| A2A feature flag | off | on (set by hand in the UI) | the agent demo's A2A lane returned `HTTP 400 ... unless the related feature flag is enabled` |
| `llmProviders/ai_c222a24e-e425-464b-a68d-ddd1f5bde6ed` | models `[gpt-4o]`, default `gpt-4o` | models `[gpt-5.2, gpt-5.6-luna, gpt-4o]`, default `gpt-5.2` | the workspace agent sends `reasoning.effort`, which `gpt-4o` rejects (`unsupported_parameter`) |
| `organizationSettings/activeLlmProvider` | `defaultModelId: gpt-4o` | `defaultModelId: gpt-5.2` | same; the setting pins its own default model |

Pre-change copies of the two entities are in `backups/usecases-ai/llm/20261024T074835Z/` (git-ignored
and local only, with no secrets in them). If the org repo's first snapshot predates these changes,
releasing it reverts A2A to failing.
