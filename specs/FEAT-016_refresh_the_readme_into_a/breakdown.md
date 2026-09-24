## Technical Breakdown — FEAT-016: Refresh the README into a comprehensive, technical, digestible entry point

This feature's deliverable is one file — `README.md` at the repo root — so its "components" are
*sections of that file* plus the verification work that makes each section's claims true. The
component table is adapted accordingly: each row is a section (or a verification pass), and the
"New or existing?" column says whether the section exists in the 5-line stub today.

Two constraints bound every section below and are repeated here rather than left implicit:

- **`specs/CONTRACT.md` is binding on names.** Every command, flag, path and module name written
  into the README is copied from `CONTRACT.md` ("CLI surface", "On-disk paths", "Package layout")
  or, where `CONTRACT.md` is silent, read verbatim out of `src/globalmart/cli.py` /
  `src/gd_agents/cli.py`. Nothing is written from memory, and nothing is invented.
- **`specs/STEERING.md` framing is the README's opening claim**, not a footnote: *the repo is the
  source of truth, never a live org*. STEERING also fixes the flag convention the quickstarts must
  present correctly — `--apply` gates live-org writes, `--dry-run` belongs only to commands whose
  writes are local files, `--check` is the CI gate form, and no command has both `--apply` and
  `--dry-run`.

---

### Components

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|
| **R1 — Title, one-paragraph framing, minimal link row** | Replaces the 5-line stub's opening. States in one sentence what GlobalMart is (a fully reproducible retail dataset — warehouse rows, LDM, 1091 metrics, 384 visualizations, 32 dashboards, AI context — defined as code), states the STEERING framing (*the repo is the source of truth, never a live org*), and names the two halves of the repo: `src/globalmart/` builds workspaces, `src/gd_agents/` talks to them. Link row: `specs/VISION.md`, `specs/REGISTRY.md`, license. | New (replaces 5 lines) | S |
| **R2 — The two goals, in two lines** | goal-01 (rebuildable from source into any org) and goal-02 (A2A/MCP federation demonstrated over GlobalMart), each one sentence with a link to `specs/goals/goal-01.md` / `goal-02.md`. This is what makes the rest of the file legible — a reader who does not know *why* there are two pipelines cannot read the diagram. | New | S |
| **R3 — Mermaid system diagram** | One `mermaid` fenced block, two subgraphs. Workspace pipeline: `layouts/workspaces/globalmart/` (YAML tree) → `split` (`config/domains.yaml`) → `generated/workspaces/globalmart-<domain>.json` (12 children) → `publish parent` / `publish domains` (`config/targets.yaml` + `--apply`) → a live org; with `data/tables/*.csv.gz` + `data/ddl/globalmart.sql` → `data load` → warehouse feeding it. Agent pipeline: `config/agents.yaml` registry → `plan()` router → fan-out lanes (`a2a/client.py` \| `mcp/lane.py`) → eight checks → `merge()` → viewer/payload. Every box names a real path or module; every arrow is a real data flow. | New | M |
| **R4 — "Map of the repo"** | A table, one line per top-level directory: `layouts/`, `generated/`, `data/`, `config/`, `src/globalmart/`, `src/gd_agents/`, `docs/`, `specs/`, `tests/`, `scripts/`, plus the gitignored runtime dirs `backups/`, `reports/`. Committed-or-not is stated for the ones where it is load-bearing (`generated/` yes — ADR 003; `data/tables/` yes — ADR 007; `backups/`/`reports/` no). Sourced verbatim from `CONTRACT.md` "On-disk paths". | New | S |
| **R5 — "Rebuild GlobalMart" quickstart** | The minimal clean-clone-to-published-org sequence, as one fenced bash block with short comments: `uv sync --extra data`; fill a profile in `config/targets.yaml` + `GLOBALMART_TOKEN__<NAME>` in `.env`; `globalmart targets inspect --target <profile>`; `globalmart data verify`; `globalmart split --check`; `globalmart rebuild --target <profile>` (rehearsal) then `--apply`. Then the per-step form for anyone who wants the chain broken open (`data load`, `publish parent`, `split`, `publish domains`, `verify`). Links out to `docs/verification.md`, `docs/publish-targets.md`, `docs/data-custody.md` rather than restating them. | New | M |
| **R6 — "Run the agent demo" quickstart** | `uv sync --extra agents`; `export GLOBALMART_TOKEN__DEMO_CLOUD` + `ANTHROPIC_API_KEY`; `gd-agents profile --host … --workspaces … --apply`; `gd-agents route` (cheap, no lane called); `gd-agents ask "…"`; `gd-agents serve` (→ `http://127.0.0.1:8900`); the `--protocol a2a\|mcp` switch on `ask`/`serve`/`rehearse`; `gd-agents registry` and `gd-agents rehearse` named in one line each. Carries the honest latency number (30–120s for a two-lane question) so a first run does not read as a hang. Links to `docs/a2a-federation.md` and `docs/a2a-gaps.md`. | New | M |
| **R7 — "Read next" docs index** | A table of the nine `docs/*.md` files plus `docs/mcp-findings.md`, one line each, so every deeper document is reachable from the front door. This is the section that discharges the "state the one-line version and link out" acceptance criterion for everything the README deliberately does not explain (how the splitter prunes, what a workspace data filter is, how custody was taken). | New | S |
| **V1 — Command verification pass** | Every command and flag written into R5/R6 is checked against the two argparse surfaces by running it — `--help` for structure, `--check`/rehearsal forms where they are offline and safe. No live-org call, per STEERING "AI Behavior". Produces the list of CONTRACT/doc discrepancies listed under *Integration Points*. | New | M |
| **V2 — Diagram/path verification pass** | Every path named in R3 and R4 is checked to exist (`layouts/workspaces/globalmart/`, `generated/workspaces/globalmart-<domain>.json` × 12, `data/tables/`, `data/ddl/globalmart.sql`, `config/*.yaml`, `src/gd_agents/{a2a,mcp,orchestrator,server}/`), and every module named in R3 is checked against `CONTRACT.md` "Package layout" and the real `src/` tree. | New | S |
| **V3 — Link + number verification pass** | Every relative link resolves to a file that exists; every asserted count (225 datasets, 1091 metrics, 384 visualizations, 32 dashboards, 12 domains, 215 tables, 174,372 rows, 14 memory items) is checked against `docs/bootstrap-provenance.md`, `docs/data-custody.md`, `config/domains.yaml` and `generated/workspaces/`. Prose line count is measured against the ~150-line budget with diagrams and code blocks excluded. | New | S |
| **T1 — `tests/test_readme.py` (link + count guard)** | Optional but cheap, and it has precedent: `tests/test_counts.py` already parses `docs/bootstrap-provenance.md` and asserts it matches the committed tree, exactly so the doc cannot silently drift. T1 does the same for the README: parse every relative link and assert the target exists; parse the count table and assert it matches `config/domains.yaml` / `data/table-manifest.json`. Wires into `.github/workflows/ci.yml` with the rest of pytest. Directly mitigates the spec's top-ranked risk (drift within weeks). | New | S |
| **~~L1 — LICENSE resolution~~** | ~~The spec's scope asks for a license link.~~ **Closed 2026-09-24 as no work** — decided: no `LICENSE` file exists, none is being added, and the link is dropped from R1. See *Decisions* below. | Closed | — |
| **C1 — `CONTRACT.md` CLI surface amendment** | Reconciles CONTRACT's CLI table with the real argparse surfaces (five missing commands, four incomplete rows) and applies the file-wide conventions the owner asked for: owning module per row, explicit write-gating column, parser-wins conflict rule, dated amendment note. Lands in the same commit as the README, per CONTRACT's own rule. Full scope in the *C1* section below. | Existing (amended) | M |

---

### Data Model

No tables, no schemas, no runtime data structures — the feature writes one Markdown file. What it
*does* have is two inventories that must be materialised before the file can be written correctly,
and one of them becomes a test fixture if T1 is built.

**1. The claim inventory** — every factual assertion the README makes, with its authority. Built
during V1–V3, kept as the working list; only the counts row survives into `tests/test_readme.py`.

| Field | Type | Meaning |
|---|---|---|
| `claim` | `str` | The sentence, command or number as written in the README |
| `kind` | `enum` | `command` \| `path` \| `module` \| `count` \| `link` |
| `authority` | `str` | Where it is checked against — `specs/CONTRACT.md`, `src/globalmart/cli.py`, `src/gd_agents/cli.py`, `docs/bootstrap-provenance.md`, `config/domains.yaml`, `data/table-manifest.json`, the filesystem |
| `verified` | `bool` | Checked at write time, not recalled |
| `discrepancy` | `str \| None` | Set where the authority disagrees with another authority — feeds the CONTRACT amendments below |

**2. The count table** — the numbers the README states, each with a committed source. These are
the only numbers worth printing, because each one has a file that can be diffed against it.

| Count | Value | Source of truth |
|---|---|---|
| `datasets` | 225 | `docs/bootstrap-provenance.md` (pinned by `tests/test_counts.py`) |
| `metrics` | 1091 | same |
| `visualization_objects` | 384 | same |
| `analytical_dashboards` | 32 | same |
| `memory_items` | 14 | same, amended 2026-09-20 (compiled by `globalmart knowledge build`) |
| `domains` | 12 | `config/domains.yaml`, and 12 files under `generated/workspaces/` |
| `workspaces published` | 13 | parent + 12 children (`docs/verification.md`) |
| `warehouse tables` | 215 | `data/table-manifest.json`, `data/ddl/globalmart.sql` |
| `warehouse rows` | 174,372 | `data/table-manifest.json` |

**3. The Mermaid diagram's node set** — not a data structure in the code sense, but it is the thing
V2 checks, so it is enumerated here as the diagram's contract. Every node is a path or a module;
no node is an abstraction with no file behind it.

| Node label | Backing artifact |
|---|---|
| `layouts/workspaces/globalmart/` | committed YAML tree, one file per object, no org id |
| `config/domains.yaml` | `DomainManifest` — membership, ids, name templates |
| `globalmart split` | `src/globalmart/split.py` (+ `closure.py`, `prune.py`, `verify.py`) |
| `generated/workspaces/globalmart-<domain>.json` | 12 committed declarative JSON children |
| `data/ddl/globalmart.sql` + `data/tables/*.csv.gz` | 215 tables, committed (ADR 007) |
| `globalmart data load` | `src/globalmart/dataload.py` → warehouse |
| `config/targets.yaml` | `TargetProfile` per publish target; zero secrets |
| `globalmart publish parent` / `publish domains` | `src/globalmart/publish.py` (`--apply` gated) |
| `globalmart verify` | `src/globalmart/verification.py` |
| `config/agents.yaml` | `gd_agents.registry.Registry` — `DEFAULT_REGISTRY_PATH` |
| `plan()` | `src/gd_agents/orchestrator/plan.py` — route + decompose, one model call |
| `A2ALane` / `MCPLane` | `src/gd_agents/a2a/client.py`, `src/gd_agents/mcp/lane.py` |
| `checks` | `src/gd_agents/orchestrator/checks.py` — the eight merge checks |
| `merge()` | `src/gd_agents/orchestrator/merge.py` |
| viewer | `src/gd_agents/server/` — `gd-agents serve`, 127.0.0.1:8900 |

---

### Integration Points

Nothing external is called. The integration surface is entirely *internal consistency* — the README
is a projection of six other sources, and every one of them can move underneath it.

| Surface | How the README touches it | What breaks it |
|---|---|---|
| `src/globalmart/cli.py` (argparse) | R5 copies command and flag spellings verbatim | A renamed flag; a subcommand moved under a different group |
| `src/gd_agents/cli.py` (argparse) | R6 copies `profile`/`route`/`rehearse`/`ask`/`serve`/`registry` and their flags verbatim | Same; also the `--protocol` choices `("a2a","mcp")` |
| `specs/CONTRACT.md` | Names for modules, paths and the CLI surface are taken from here first | A CONTRACT edit that is not mirrored into the README |
| `specs/STEERING.md` | The opening framing; the `--apply` / `--dry-run` / `--check` convention as presented | A change to the flag convention |
| `docs/*.md` (10 files) | R7 links to each; R5/R6 link out instead of restating | A doc renamed or removed → dead link (T1 catches) |
| `specs/VISION.md`, `specs/REGISTRY.md`, `specs/goals/goal-0{1,2}.md` | Linked from R1/R2 as-is; out of scope to edit | A rename |
| `config/domains.yaml`, `config/targets.yaml`, `config/agents.yaml`, `data/table-manifest.json` | Counts and file names in R3/R4 | A 13th domain; a table added |
| GitHub's Mermaid renderer | R3 renders with no build step | Only a Mermaid syntax error; GitHub support is stable |
| `.github/workflows/ci.yml` | T1 runs inside the existing pytest job — no new workflow | — |
| `pyproject.toml` `[project.scripts]` | Confirms both console entry points exist: `globalmart = globalmart.cli:main`, `gd-agents = gd_agents.cli:main` | An entry point rename |
| `pyproject.toml` `[project.optional-dependencies]` | `uv sync --extra data` (warehouse drivers) and `--extra agents` (the model client) are both required by the quickstarts and neither is default | An extra renamed |

**Discrepancies found while reading — these are the integration points that actually bite.** Each
is a place where two authorities disagree, so the README cannot simply copy one of them.

1. **`CONTRACT.md`'s CLI table is incomplete.** `src/globalmart/cli.py` registers subcommands the
   table does not list: `globalmart knowledge build [--check]` (FEAT-008), `globalmart data generate`
   (FEAT-007), `globalmart data ensure`, `globalmart datefilters bind` (FEAT-011), and
   `globalmart targets inspect` — the last of which `docs/publish-targets.md` and
   `docs/verification.md` both put in their runbooks, and which R5 needs. Per CONTRACT's own rule
   ("change this file *first*, in the same commit, and say so in that feature's breakdown"), the
   README work includes appending these rows to `CONTRACT.md`'s CLI surface table. It documents
   existing commands; it invents nothing.
2. **`split`'s real flags exceed the CONTRACT row.** CONTRACT has
   `globalmart split [--domains-file ...] [--from <layout>] [--check]`. The parser also carries
   `--out`, `--only`, `--metric-policy {dataset-fit,reachable}` and `--dry-run` — and `--from` is an
   alias of `--source` (`dest="source"`). `--dry-run` here is correct under STEERING, since split's
   writes are local files. R5 shows `split` and `split --check`; the rest is left to
   `docs/domain-split.md`.
3. **`publish parent` carries `--source`, `--workspace-name`, `--no-backup`, `--standalone-copy`**
   beyond CONTRACT's row, and `publish domains` carries `--only`, `--keep-going`, `--no-backup`,
   `--standalone-copy`. R5 shows only `--target` and `--apply` and links to
   `docs/publish-targets.md` — the others are recovery and edge-case flags that belong in the doc,
   not the front door.
4. **No `LICENSE` file, and no `license` key in `pyproject.toml`.** Resolved 2026-09-24: none is
   being added and the README carries no license link. See *Decisions*.
5. **`docs/a2a-federation.md`'s layout block is stale in one line**: it prints `mcp/ empty —
   FEAT-014`, while `src/gd_agents/mcp/` now holds `lane.py`, `client.py`, `tools.py`, `probe.py`.
   Out of scope to fix (the spec forbids editing `docs/`), but R3's diagram must draw `MCPLane` as
   real, not as a planned box, and R6 must present `--protocol mcp` as working.

---

### Test Strategy

There is no runtime behaviour to unit-test. The testable surface is *whether the README's claims are
true*, and that splits cleanly into three tiers.

**Automated (`tests/test_readme.py`, component T1) — the drift guard.**

| Test | Asserts |
|---|---|
| `test_every_relative_link_resolves` | Every `](…)` target that is not `http(s)://` exists on disk, relative to the repo root. Covers all ten `docs/` links, the four `specs/` links, and any `config/`/`data/` reference. |
| `test_the_counts_match_their_sources` | The count table matches `config/domains.yaml` (12 domains), `generated/workspaces/` (12 files), `data/table-manifest.json` (215 tables, 174,372 rows). Mirrors what `tests/test_counts.py` already does for `docs/bootstrap-provenance.md`. |
| `test_every_command_shown_is_a_real_subcommand` | Each `globalmart …` / `gd-agents …` line in a fenced block parses against the real argparse parsers (`build_parser()` for globalmart; `main(["--help"])`-style introspection for gd-agents), with `parse_args` on a rehearsal-safe form. Nothing is executed. |
| `test_the_prose_budget_holds` | Prose lines (excluding fenced blocks, tables and the Mermaid block) stay under the ~150-line ceiling the acceptance criteria set. Asserted with slack, so an honest edit is not a build failure. |

**Manual, once, at write time (components V1–V3) — the correctness pass.**

- Run `globalmart --help` and every subcommand's `--help`; run `gd-agents --help` and each of
  `profile`/`route`/`rehearse`/`ask`/`serve`/`registry --help`. Confirm each flag spelled in R5/R6
  exists, including `--protocol` choices and `--token-env`'s default
  `GLOBALMART_TOKEN__DEMO_CLOUD`.
- Run the offline commands for real: `globalmart data verify`, `globalmart split --check`,
  `globalmart domains validate --strict`, `gd-agents registry`. These write nothing and contact no
  host, so they are safe under STEERING's "do not execute against a live GoodData host" rule, and
  they prove R5's first half literally.
- Do **not** run `publish`, `data load --apply`, `rebuild --apply`, `gd-agents profile --apply`,
  `ask`, `rehearse` or `serve` — they need a live org, credentials and (for the agent side) an
  `ANTHROPIC_API_KEY`. Their correctness is established by `--help` parity plus the fact that
  `docs/a2a-federation.md` and `docs/verification.md` record real measured runs of exactly those
  invocations.
- Render the Mermaid block: paste into GitHub's preview (or a Mermaid live editor) and confirm it
  draws. The spec's own risk row makes a plain-text tree the fallback if it does not.

**Manual, by a second reader — the acceptance test the spec actually names.**

The first acceptance criterion is a comprehension test, not a lint: give the file to someone with no
prior context and ask them to state, without opening a second file, (a) what GlobalMart is, (b) what
the parent/domain split is, and (c) where to run the A2A demo. If any of the three needs a second
file, the section that should have carried it is the one to fix. This is the only test that can
fail for a reason `tests/test_readme.py` cannot see, and it is the one that decides the feature.

---

### Total Effort Estimate

| Scale | Meaning |
|---|---|
| S | A few hours |
| M | 1–3 days |
| L | 1–2 weeks |
| XL | More than a sprint — consider splitting the feature |

| Component | Effort |
|---|---|
| R1 — Title, framing, link row | S |
| R2 — The two goals | S |
| R3 — Mermaid system diagram | M |
| R4 — Map of the repo | S |
| R5 — Rebuild quickstart | M |
| R6 — Agent demo quickstart | M |
| R7 — Read-next docs index | S |
| V1 — Command verification | M |
| V2 — Diagram/path verification | S |
| V3 — Link + number verification | S |
| T1 — `tests/test_readme.py` | S |
| L1 — LICENSE resolution | S |

**Overall:** **M — 2 to 3 days**, at the top of the spec's `s` appetite (1–3 days) rather than with
room to spare. Revised upward on 2026-09-24: the original 1.5–2 day estimate predated the decision to
amend `CONTRACT.md` properly (component **C1**, M) rather than append four rows to it. L1 closing as
no work returns a few hours; C1 costs more than that. If the feature runs over, C1's file-wide
conventions are the part to defer — the correctness fixes (missing commands, incomplete flag rows)
are not optional, since the README's quickstarts are written from them.

The writing is not the work. R1/R2/R4/R7 are a few hours between them. The cost is concentrated in
three places: V1, because every flag has to be *run*, not recalled, and the run surfaced five
authority discrepancies that each need a small decision; R3, because a diagram that is honest about
both pipelines at module granularity takes two or three passes to get legible without becoming a
class diagram; and R5/R6, because "the commands run" is a claim, and the offline half of each
sequence is actually executed to earn it.

Two things keep this from growing. The spec's Out of Scope is unusually firm — no `docs/` edits, no
auto-generation, no screenshots, no API reference — and the ~150-line prose budget is a hard
tiebreaker rather than a preference. If R5 starts explaining what a workspace data filter is, or R6
starts explaining the eight merge checks, the section is over budget by construction and the
sentence becomes a link. T1 is the only component that could be dropped without failing an
acceptance criterion; it is kept because the spec's highest-likelihood risk is drift, and a parsing
test is the cheapest thing that has ever fixed that here.

---

### Implementation Order

Verification comes before writing, not after. Every acceptance criterion is a claim about
correspondence with the repo, so the material has to be established before the prose is committed to
— writing first and checking after is how a confident-sounding wrong command gets shipped.

1. **V1 — Command verification pass.** Run `--help` across both CLIs; run the four offline commands
   (`data verify`, `split --check`, `domains validate --strict`, `gd-agents registry`). Produce the
   exact command sequences R5 and R6 will contain. *Blocks R5, R6.*
2. **V2 — Diagram/path verification pass.** Enumerate the real paths and modules; confirm every
   node in the diagram's contract table above. *Blocks R3, R4.*
3. **V3 — Link + number verification pass.** Fix the count table against its committed sources;
   confirm every `docs/` and `specs/` link target exists. *Blocks R7, and the counts in R1.*
4. **C1 — `CONTRACT.md` CLI surface amendment.** Append the missing rows (`knowledge build`,
   `data generate`, `data ensure`, `datefilters bind`, `targets inspect`), widen the `split` /
   `publish parent` / `publish domains` rows to the real flag sets, and apply the file-wide
   conventions from the *C1* section: owning-module column across all rows, explicit write-gating
   column, parser-wins conflict rule, staleness rule, dated amendment note. Verified by running
   `--help` on every listed command. Same commit as the README, per CONTRACT's own rule. *Blocks
   R5 — the README must not be the first place a command is written down.* Consumes V1's output,
   so it runs after V1 rather than in parallel with it.
5. *(L1 — LICENSE — closed as no work on 2026-09-24; the README carries no license link. Step
   retained as a number so the ordering below is not renumbered.)*
6. **R1 — Title, framing, link row.** Sets the file's voice and the STEERING framing everything else
   sits under.
7. **R2 — The two goals.** Immediately after R1, because R3 is unreadable without it.
8. **R3 — Mermaid system diagram.** The centrepiece, and the section most likely to need a second
   pass once R5/R6 exist and show which arrows readers actually follow.
9. **R4 — Map of the repo.** Directly after the diagram: the diagram names the paths, the map
   explains them.
10. **R5 — Rebuild quickstart.** Written straight from V1's verified sequences.
11. **R6 — Agent demo quickstart.** Same.
12. **R7 — Read-next docs index.** Last of the prose, because it is the catch-all for everything the
    earlier sections chose to link rather than explain — it cannot be finalised until they are.
13. **Prose budget check and trim.** Measure; cut to the ~150-line ceiling. Anything cut becomes a
    link in R7.
14. **T1 — `tests/test_readme.py`.** Written against the finished file, wired into the existing
    pytest job in `.github/workflows/ci.yml`.
15. **Second-reader comprehension test.** The acceptance criterion that decides the feature. Any
    failure loops back to the specific section, not to the whole file.

Steps 1–3 are independent of each other and can run in parallel; step 4 (C1) waits on step 1, since
it records the same parser surface V1 establishes. Steps 6–12 are strictly sequential:
each section's scope depends on what the previous one already said, and that dependency is exactly
what keeps the file from repeating itself.

---

### Decisions — resolved 2026-09-24

All three items below were raised as `[DECISION NEEDED]` and answered by the owner on 2026-09-24.
They are settled; downstream stages (`/tasks`, implementation) treat them as given.

1. **License — dropped from the README.** Owner: "I don't care." There is no `LICENSE` file at the
   repo root and no `license` key in `pyproject.toml`, and indifference is not a license grant — a
   README that links to a license the repo does not have would assert something false, and one that
   picks a license would decide it by accident. **R1 ships without the license link row.** If the
   repo is ever published outside the owner's control, adding a `LICENSE` is its own decision and
   its own commit; it is not a README change. Component L1 is therefore closed as *no work*, and
   R1's link row carries `specs/VISION.md` and `specs/REGISTRY.md` only.

2. **Mermaid — confirmed.** Owner had no preference once the trade-off was explained. R3 is a
   `mermaid` fenced block: it renders natively on GitHub with no build step, it diffs as text so a
   path rename is visible in review, and it stays checkable against the code it depicts — a
   checked-in PNG would be the first artifact in this repo that cannot be. R3 stays **M**, not L.
   The spec's corresponding Open Question is answered; no second source of truth is introduced.

3. **`CONTRACT.md` is amended in the same commit, and brought up to standard while open.** Owner:
   "include it properly and make sure contract is written using best practices in mind." This is
   broader than the minimal fix and is accepted deliberately — see **C1** below, which supersedes
   the narrower amendment described in *Integration Points*.

---

### C1 — `CONTRACT.md` amendment (accepted scope)

CONTRACT's own rule is that a change to a shared name or signature lands in `CONTRACT.md` first, in
the same commit. The README cannot document a CLI surface that contradicts the pinned contract, so
the contract is corrected here rather than worked around.

**Effort: M.** This raises the feature's overall estimate from M to M-plus and is the single largest
addition to the `s` appetite. It is documentary work — it records what the parsers already do and
invents no interface.

**Correctness — the drift that must be fixed:**

| # | Gap | Fix |
|---|---|---|
| 1 | Five commands in `src/globalmart/cli.py` are absent from the CLI surface table: `knowledge build`, `data generate`, `data ensure`, `datefilters bind`, `targets inspect` | Add one row each, flags read from the parser, not from memory |
| 2 | `globalmart split` row omits `--out`, `--only`, `--metric-policy {dataset-fit,reachable}`, `--dry-run`, and does not record that `--from` is an alias of `--source` (`dest="source"`) | Complete the row; note the alias |
| 3 | `globalmart publish parent` row omits `--source`, `--workspace-name`, `--no-backup`, `--standalone-copy` | Complete the row |
| 4 | `globalmart publish domains` row omits `--only`, `--keep-going`, `--no-backup`, `--standalone-copy` | Complete the row |

**Best practices — applied to the whole file while it is open.** The owner asked for the contract to
be *written properly*, not merely patched, so the amendment also establishes these and applies them
uniformly rather than only to the new rows:

- **One source of truth per fact.** Every CLI row is generated from, and checkable against, the real
  argparse parser. Where the contract and a parser disagree, the parser wins and the contract is
  wrong — state that rule explicitly in the file so the next reader knows which way to resolve it.
- **Every row carries its owning module.** A command row that does not name the module implementing
  it cannot be verified, and forces a grep. Backfill the column across all rows, not just new ones.
- **Mark the write-gated commands explicitly.** STEERING's `--apply` rule is binding and currently
  implicit in the table. Add a column stating, per command, whether it writes to a live org
  (`--apply` gated), writes local files (`--dry-run`), or is read-only. This is the single most
  load-bearing fact about any command here and it should not require reading the parser to learn.
- **No flag appears in prose that is absent from a row.** Prose descriptions drift faster than
  tables; the table is the contract, prose is commentary.
- **Date and scope the amendment.** A short "amended 2026-09-24 — CLI surface reconciled against
  `src/globalmart/cli.py` and `src/gd_agents/cli.py`" note, so the next divergence is bisectable.
- **State the staleness rule.** One line at the top of the CLI section: this table is amended in the
  same commit as any change to a parser, and `tests/test_cli.py` is where that is enforced.

**Verification.** The amended table is checked by running `--help` on every listed command (offline,
no live-org call, per STEERING "AI Behavior") — the same V1 pass that verifies the README's
quickstarts, extended to cover every row rather than only the rows the README shows.

**Out of scope for C1:** module ownership, `TargetProfile`, placeholder tokens, domain manifest
types, on-disk paths and test fixture ownership are read but not rewritten. Only the CLI surface
section is amended. If reading those sections surfaces further drift, it is recorded as a finding
for a follow-up feature, not fixed here.
