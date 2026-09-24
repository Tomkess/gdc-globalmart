## Tasks — FEAT-016: Refresh the README into a comprehensive, technical, digestible entry point

> Appetite: `s` (1–3 days)  ·  Generated: 2026-09-24

- [x] 1. Verify the `globalmart` CLI surface: run `--help` on every subcommand in `src/globalmart/cli.py`, then run the offline/rehearsal forms `globalmart data verify`, `globalmart split --check`, `globalmart domains validate --strict` for real. Record the exact flag spellings and the five commands CONTRACT's CLI table is missing (`knowledge build`, `data generate`, `data ensure`, `datefilters bind`, `targets inspect`) and the three rows that are narrower than the real parser (`split`, `publish parent`, `publish domains`).
       Pre: none
       AC: #3
- [x] 2. Verify the `gd-agents` CLI surface: run `--help` on `profile`/`route`/`rehearse`/`ask`/`serve`/`registry` in `src/gd_agents/cli.py`, then run `gd-agents registry` for real. Confirm the `--protocol {a2a,mcp}` choice and `--token-env`'s default `GLOBALMART_TOKEN__DEMO_CLOUD`. Do not run `profile --apply`, `ask`, `rehearse` or `serve` — no live-org call, no `ANTHROPIC_API_KEY` spend.
       Pre: none
       AC: #3
- [x] 3. Verify the Mermaid diagram's node set: confirm every path (`layouts/workspaces/globalmart/`, `generated/workspaces/globalmart-<domain>.json` × 12, `data/tables/`, `data/ddl/globalmart.sql`, `config/*.yaml`) and module (`src/globalmart/split.py`+`closure.py`+`prune.py`+`verify.py`, `src/gd_agents/{a2a,mcp,orchestrator,server}/`) named in breakdown.md's node table exists on disk and matches `CONTRACT.md` "Package layout".
       Pre: none
       AC: #2
- [x] 4. Verify links and counts: confirm every `docs/*.md` and `specs/*.md` link target used in the draft exists, and check the count table (225 datasets, 1091 metrics, 384 visualizations, 32 dashboards, 12 domains, 13 workspaces published, 215 warehouse tables, 174,372 rows, 14 memory items) against `docs/bootstrap-provenance.md`, `docs/data-custody.md`, `config/domains.yaml`, `generated/workspaces/`, `data/table-manifest.json`.
       Pre: none
       AC: #2
- [x] 5. Amend `CONTRACT.md`'s CLI surface table: append one row each for `knowledge build`, `data generate`, `data ensure`, `datefilters bind`, `targets inspect`, using the flags recorded in task 1 — nothing written from memory.
       Pre: task 1 complete
       AC: #3
- [x] 6. Widen the `split`, `publish parent`, `publish domains` rows in `CONTRACT.md` to their real flag sets from task 1 (`split` gains `--out`, `--only`, `--metric-policy {dataset-fit,reachable}`, `--dry-run`, and a note that `--from` aliases `--source`; `publish parent` gains `--source`, `--workspace-name`, `--no-backup`, `--standalone-copy`; `publish domains` gains `--only`, `--keep-going`, `--no-backup`, `--standalone-copy`).
       Pre: task 1 complete
       AC: #3
- [x] 7. Apply the file-wide CONTRACT conventions to the whole CLI surface section (not just the new/widened rows): an owning-module column on every row, an explicit write-gating column (`--apply`-gated live write / `--dry-run` local write / read-only), a stated "parser wins on conflict" rule, a stated staleness rule pointing at `tests/test_cli.py`, and a dated amendment note ("amended 2026-09-24 — CLI surface reconciled against `src/globalmart/cli.py` and `src/gd_agents/cli.py`"). Verify by re-running `--help` on every row, not only the rows tasks 5–6 touched.
       Pre: tasks 5, 6 complete
       AC: #3
- [x] 8. Write R1 — title, one-paragraph framing, link row: what GlobalMart is (fully reproducible retail dataset defined as code), the STEERING framing ("the repo is the source of truth, never a live org"), the two-package split (`src/globalmart/` builds workspaces, `src/gd_agents/` talks to them), and a link row to `specs/VISION.md` and `specs/REGISTRY.md` — no license link, per the 2026-09-24 decision.
       Pre: none
       AC: #1
- [x] 9. Write R2 — the two goals in two lines: goal-01 (rebuildable from source into any org) and goal-02 (A2A/MCP federation demonstrated over GlobalMart), each one sentence linking to its `specs/goals/goal-0{1,2}.md` file.
       Pre: task 8 complete
       AC: #1
- [x] 10. Draft R3's Mermaid diagram: one fenced `mermaid` block, two subgraphs — workspace pipeline (`layouts/workspaces/globalmart/` → `split` → `generated/workspaces/globalmart-<domain>.json` ×12 → `publish parent`/`publish domains` (`--apply`) → live org; `data/tables/` + `data/ddl/globalmart.sql` → `data load` → warehouse) and agent pipeline (`config/agents.yaml` → `plan()` → fan-out lanes `A2ALane`/`MCPLane` → checks → `merge()` → viewer). Every box is a path or module verified in task 3.
       Pre: tasks 3, 9 complete
       AC: #2
- [x] 11. Render-check the Mermaid block (GitHub preview or a Mermaid live editor) and do one legibility pass: confirm both subgraphs are readable at module/directory granularity and neither collapses into a class diagram. Fall back to a plain-text tree diagram only if Mermaid genuinely fails to render.
       Pre: task 10 complete
       AC: #2
- [x] 12. Write R4 — "map of the repo" table, one line per top-level directory (`layouts/`, `generated/`, `data/`, `config/`, `src/globalmart/`, `src/gd_agents/`, `docs/`, `specs/`, `tests/`, `scripts/`, plus gitignored `backups/`, `reports/`), stating committed-or-not where load-bearing (`generated/` yes — ADR 003; `data/tables/` yes — ADR 007; `backups/`/`reports/` no). Sourced verbatim from `CONTRACT.md` "On-disk paths".
       Pre: task 11 complete
       AC: #1
- [x] 13. Write R5 — "Rebuild GlobalMart" quickstart: the verified clean-clone-to-published-org sequence from task 1 (`uv sync --extra data`; fill `config/targets.yaml` + `.env`; `globalmart targets inspect`; `globalmart data verify`; `globalmart split --check`; `globalmart rebuild --target <profile>` rehearsal then `--apply`), plus the per-step breakout, linking to `docs/verification.md`, `docs/publish-targets.md`, `docs/data-custody.md` instead of restating them.
       Pre: tasks 1, 7 complete
       AC: #3
- [x] 14. Write R6 — "Run the agent demo" quickstart: the verified sequence from task 2 (`uv sync --extra agents`; env vars; `gd-agents profile --apply`; `gd-agents route`; `gd-agents ask "…"`; `gd-agents serve` → `http://127.0.0.1:8900`; the `--protocol a2a|mcp` switch; `registry` and `rehearse` named in one line each), carrying the honest 30–120s latency note, linking to `docs/a2a-federation.md` and `docs/a2a-gaps.md`.
       Pre: task 2 complete
       AC: #3
- [x] 15. Write R7 — "read next" docs index: one line each for the ten `docs/*.md` files, so every deeper document is reachable from the front door, discharging the "state the one-line version and link out" criterion for everything R1–R6 chose not to explain.
       Pre: tasks 13, 14 complete
       AC: #5
- [x] 16. Measure the finished file's prose line count (excluding fenced blocks, tables, the Mermaid block) against the ~150-line budget and trim. Anything cut becomes a link into R7 rather than a deletion of the claim.
       Pre: tasks 8, 9, 12, 13, 14, 15 complete
       AC: #4
- [x] 17. Write `tests/test_readme.py`: assert every relative link resolves, the count table matches `config/domains.yaml` / `generated/workspaces/` / `data/table-manifest.json`, every `globalmart …`/`gd-agents …` fenced-block line parses against the real argparse parsers, and the prose line count stays under budget with slack. Wire into the existing pytest job in `.github/workflows/ci.yml`.
       Pre: task 16 complete
       AC: #2, #3, #4 (regression guard against drift)
- [ ] 18. Run the second-reader comprehension test: hand the finished README to someone with no prior context and confirm, without them opening a second file, they can state what GlobalMart is, what the parent/domain split is, and where to run the A2A demo. Any gap sends the specific section back to its task, not the whole file.
       Pre: task 16 complete
       AC: #1
