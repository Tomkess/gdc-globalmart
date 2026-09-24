---
abandoned_at: null
abandoned_reason: null
appetite: s
blocked_at: null
blocked_by: null
confidence: medium
created: '2026-09-24'
cycle: null
depends_on: []
enables: []
goal: goal-01
id: feat-016
links: []
name: 'Refresh the README into a comprehensive, technical, digestible entry point:
  few words, diagrams over prose, covering what GlobalMart is, how the repo rebuilds
  it, and how the A2A/MCP orchestrator runs'
sources: []
status: in-progress
tags: []
updated: '2026-09-24'
---

## Summary

The root `README.md` is five lines: a name, one sentence, and a pointer to `specs/`. Everything a
newcomer actually needs — what GlobalMart is, how the parent/domain split works, how to rebuild
into a fresh org, how the A2A/MCP orchestrator runs and what `gd-agents` commands exist — is spread
across nine files under `docs/` and thirteen features under `specs/`, none of it reachable from the
front door. This feature replaces the stub with a comprehensive but tightly-worded README: a
system diagram, a rebuild quickstart, and an orchestrator quickstart, each backed by a link to the
detailed doc rather than a restatement of it. It matters to goal-01 because "rebuildable from
source" is only true in practice if the first file a cloner opens tells them how — today it tells
them to go read `specs/`.

## Appetite

`s` — 1–3 days

## Acceptance Criteria

- [ ] Given a fresh clone with no prior context, when a reader opens `README.md`, then they can
      state in one sentence what GlobalMart is, what the parent/domain split is, and where to run
      the A2A demo — without opening a second file.
- [ ] Given the README's system diagram, when compared against `layouts/`, `generated/workspaces/`,
      `data/`, and `src/gd_agents/`, then every box in the diagram names a real path or module and
      every arrow matches an actual data flow (capture → split → publish; question → router →
      fan-out → merge).
- [ ] Given the "rebuild from source" section, when a reader follows it verbatim on a clean clone
      plus org credentials, then the commands run (`profile`/`route`/`ask`/`serve` for the agent
      side; the existing bootstrap/publish/split commands for the workspace side) — no step
      references a command, flag, or file that does not exist.
- [ ] Given the whole file, when measured, then it stays under ~150 lines of prose (diagrams and
      code blocks excluded) — comprehensive means well-organized and linked, not long.
- [ ] Given any claim that duplicates a `docs/*.md` file (e.g. how the splitter prunes, what a
      workspace data filter is), then the README states the one-line version and links out rather
      than re-explaining it.

## Scope

- Rewrite `README.md` at the repo root only.
- One architecture diagram (Mermaid, since GitHub renders it natively with no build step) showing
  the two halves of the repo: the workspace pipeline (parent YAML → split → domain JSON → publish)
  and the agent pipeline (registry → router → fan-out lanes → merge → viewer).
- A "rebuild GlobalMart" quickstart: the minimal command sequence from clean clone to a published
  org, linking to `docs/` for anything beyond the happy path.
- A "run the agent demo" quickstart: `gd-agents profile` → `route`/`rehearse` → `serve`, linking to
  `docs/a2a-federation.md` and `docs/a2a-gaps.md` for the protocol write-up.
- A short "map of the repo" section: what lives in `layouts/`, `generated/`, `data/`, `src/`,
  `docs/`, `specs/` — one line each — so a reader can navigate without grepping.
- Badges/links kept minimal: license, and a link to `specs/VISION.md` and `specs/REGISTRY.md`.

## Out of Scope

- Rewriting or reorganizing any file under `docs/` — this feature links to them, it does not fix
  them.
- API reference documentation (CLI `--help` output already covers this; not duplicated in README).
- Auto-generating the README from source (e.g. from `domains.yaml` or the registry) — a future
  feature if the manual version drifts often enough to justify it; out of scope at `s` appetite.
- Screenshots or rendered dashboard images (the viewer is local-only and has no stable state to
  capture).
- Rewriting `specs/VISION.md` or `specs/REGISTRY.md` — README links to them as-is.

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Diagram or command sequence drifts from reality within weeks (both pipelines are under active development — 13 files changed this week alone) | high | medium | Keep the diagram at module/directory granularity, not function-level; acceptance criteria above require verifying commands against what actually exists at write time, not from memory |
| "Comprehensive but short" is a real tension — reviewer disagreement on what to cut | medium | low | Anchor on the acceptance criteria's one-sentence test and 150-line budget as the tiebreaker, not taste |
| Mermaid diagram doesn't render in every context the README is viewed in (e.g. some IDE previews) | low | low | GitHub and most modern Markdown viewers support Mermaid natively; fall back to a plain-text tree diagram only if this proves false during review |

## Dependencies

- **Depends on:** none — the underlying docs (`docs/a2a-federation.md`, `docs/a2a-gaps.md`,
  `docs/domain-split.md`, etc.) and the `gd-agents` CLI already exist and are stable enough to
  document.
- **Enables:** none directly; improves onboarding for anyone approaching goal-02's demo work fresh.

## Related Research

No sources enriched yet (`meridian enrich feat-016 <source>`). Grounding for this spec came from
reading the repo directly rather than an external source:

- `README.md` (current): 5 lines, no diagram, no command reference.
- `docs/` (9 files, ~74 KB): the actual depth of documented material — federation design, protocol
  gaps, domain split mechanics, data custody, publish targets, verification, knowledge corpus.
- `specs/VISION.md` + `specs/goals/goal-01.md`, `goal-02.md`: the two goals a README should make
  legible at a glance — rebuildability and the A2A/MCP demo.
- `src/gd_agents/cli.py`: the actual command surface (`profile`, `route`, `rehearse`, `ask`,
  `serve`, `registry`) that any quickstart must match verbatim.
- `specs/STEERING.md`: confirms no root `CONTRACT.md` exists yet in this repo, and that the repo
  frames itself as source-of-truth-over-live-org throughout — the README should open with that
  framing, not bury it.

## Open Questions

- Does a Mermaid diagram fit the "diagraphs" ask, or did the idea mean something more literal
  (e.g. a rendered image)? Proceeding with Mermaid as the default technical-README convention;
  flag during `/breakdown` if an image-based diagram is actually wanted.
- Should the README eventually be assembled from `domains.yaml` / the registry to prevent drift, or
  is manual upkeep acceptable at this repo's size? Left as a future idea rather than blocking this
  one (see Out of Scope).
