# Verification

goal-01 claims that a clean clone plus credentials rebuilds GlobalMart "with every
visualization executing successfully and no manual step". This is the harness that decides
whether that sentence is true today.

```bash
globalmart verify --target demo-cloud                    # the four axes
globalmart verify --target demo-cloud --list-only        # check structure, execute nothing
globalmart verify --target demo-cloud --fail-on-empty    # treat zero rows as a failure
globalmart verify equivalence --target-a demo-cloud --target-b usecases-ai
globalmart rebuild --target <profile>                    # the whole chain, rehearsal
globalmart rebuild --target <profile> --apply
```

Exit codes: **0** everything holds, **1** verification failed, **2** configuration or
credential error. `verify` is read-only, so it takes no `--apply` and no `--dry-run`.

## The four axes

**1. Executions succeed.** Every visualization in all 13 workspaces is run against the
warehouse through `sdk.tables.for_visualization(...)`. This matters because *no field on a
visualization marks it as broken* — a workspace can publish cleanly, pass every structural
check, and still render an error on every tile, because whether something computes depends
on the LDM, the warehouse and the data, none of which the layout knows about. Running it is
the only way to find out.

**2. The right objects arrived.** Each workspace's live object counts are compared against
counts derived from the repo: the parent against `layouts/workspaces/globalmart/`, each
child against **its own** `generated/workspaces/globalmart-<domain>.json`. A child is never
compared against the parent's numbers.

**3. The split lost nothing.** Every parent dashboard and visualization must appear in at
least one child, and no child may carry a dataset it cannot explain — recomputed from the
artifact itself, not by calling FEAT-004's closure code. That independence is the point: it
catches a stale generated file, a hand-edited one, or a child published from an artifact
that no longer matches the parent, none of which FEAT-004's unit tests can see.

**4. The result is org-independent.** `verify equivalence` fetches one workspace from two
orgs, masks what is allowed to differ with FEAT-002's `mask_parameters()`, and diffs the
rest path by path.

## What this harness cannot tell you

Stated here and printed at the top of every report, because a limit that lives only in a
spec is a limit nobody knows about:

- **A visualization that computes and returns wrong numbers passes.** The harness proves
  execution, never semantics. `row_count` is recorded per visualization, so a run-over-run
  collapse from 50,000 rows to 3 is visible to whoever compares two runs — but nothing
  automatic notices.
- **Dashboard rendering is never exercised.** Executions go through visualization objects.
  Layout, drills and filter-context wiring can be broken on a dashboard that is green here.
- **AI context is counted, never tested.** That memory items and parameters survived the
  publish is asserted structurally. A regression that leaves them present but wrong passes.
- **Empty results are surfaced, not judged.** See below.

## `EMPTY` is its own status

A visualization that executes and returns zero rows is not an error — GlobalMart has
legitimately empty slices. But folding it into `OK` would let a completely unloaded
warehouse pass the goal-01 claim in silence, which is the worse failure. So `EMPTY` is
counted separately, always listed, and `--fail-on-empty` promotes it to a failure.

Above 50% empty in one workspace the report emits a workspace-level warning naming the
likely cause, because at that ratio the diagnosis is almost never "these visualizations are
individually wrong".

## One workspace-wide cause is one finding

A workspace that inherits a workspace-data-filter *definition* with no *value* set fails
**every** execution with HTTP 400. Without a preflight that reads as 384 visualization
defects instead of one configuration fault — the predecessor's single most valuable finding.
So the WDF preflight runs before execution and its warning is printed above the per-object
list. FEAT-001 defaults to `WdfPolicy.DROP`, so in a repo-built org it should always come
back clean; the check exists to prove that rather than assume it.

Separately, when every failure in a workspace shares one taxonomy category, the report says
so once rather than repeating it N times.

## The workspace set comes from the repo

Thirteen: the parent plus one per domain in `domains.yaml`. Never from `list_workspaces()`.
A harness that asks the org what to verify can pass by verifying less than it should, and
that failure is invisible — the report looks clean, it is just shorter than it ought to be.
A workspace the repo expects and the org lacks is a failure, not an absence.

## Retries, timeouts and throttling

- Only `TRANSIENT_5XX` and `RATE_LIMITED` are retried, bounded by `--max-retries`
  (default 2). Retrying a deterministic failure just makes it a slow deterministic failure.
- `attempts` is recorded per visualization, so a pass on attempt 3 is visible in the JSON
  and never silently green.
- Each execution is bounded by `--viz-timeout` (default 180s), enforced by an inner daemon
  thread because `ThreadPoolExecutor` cannot cancel a task already in flight.
- One concurrency budget for the whole run, not one per workspace. On a 429, or three
  consecutive 5xx, it halves for the remainder of the run and the event is recorded.

## The reports

`--output-dir` (default `reports/`, gitignored) gets two files:

- **`verification_result.json`** — schema-versioned (`schema_version: 1`), the CI gate and
  the historical record. Carries the effective options, so a run is reproducible from its
  own output.
- **`verification_report.md`** — broken first, then empty, then skipped. Regenerable from
  the JSON alone, so an old run can be re-read months later with no host involved.

## The cold rebuild

`globalmart rebuild` chains every other command in one process — verify data, load the
warehouse, publish the parent, split, publish the children, verify — calling each owning
feature's function directly rather than shelling out, so `--apply` and exceptions propagate
as values. Each step still prints the CLI command that reproduces it alone, because "the
script did it" is a poor answer when one step fails.

**The empty-org probe is what makes the claim honest.** A cold rebuild that only ever runs
against an already-populated org proves nothing about a cold start. So the org is probed
first, `started_from_empty_org` is recorded in the report, and finding an existing
GlobalMart workspace aborts the run unless `--allow-existing` is passed.

### Runbook for a fresh org

```bash
# 1. Fill in a profile in config/targets.yaml, then confirm what the host says:
globalmart targets inspect --target <profile>

# 2. Rehearse — writes nothing, prints the step plan:
globalmart rebuild --target <profile>

# 3. Do it:
uv sync --extra data
globalmart rebuild --target <profile> --apply
```
