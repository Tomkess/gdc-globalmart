# 003 — What under `generated/` is committed, and what is regenerated

**Status:** Accepted
**Date:** 2026-09-18
**Context:** feat-004 (domain splitter), feat-005 (data generator); clarifies ADR 001

## Decision

`generated/` holds two kinds of output and they are treated oppositely:

- **`generated/workspaces/*.json` — committed.** The 12 derived domain layouts are reviewable
  semantic content. A diff there says "this metric left the HR child" or "this dataset is no longer
  pruned", which is exactly the review surface ADR 001 was created to produce.
- **The warehouse rows — never committed.** Hundreds of megabytes of CSV with no meaningful git
  delta. Committing them would make the repo unusable within a few iterations.

What is committed for data instead: the DDL and `data/archive-manifest.json`, which pins the archive
version, its URL, its sha256 and every table's row count and checksum. The manifest is a sharper
review surface than a CSV diff nobody reads — a change to it is a deliberate data change.

> **Amended 2026-09-18.** This ADR originally said data is "reproduced from the generator plus its
> recorded seed". The generator was descoped to FEAT-007 and FEAT-005 now takes custody of the
> existing bytes instead, so data is **fetched and verified against a committed manifest** rather
> than regenerated. The principle is unchanged and the split by reviewability still holds; only the
> recovery mechanism differs — re-fetch the pinned archive rather than re-run a seed. The local
> cache (`.cache/globalmart-data/`) is gitignored exactly as `generated/data/**` was.

The rule in one line: **commit what a human reviews, regenerate what a machine consumes.**

## Alternatives Considered

| Option | Pros | Cons |
|---|---|---|
| Chosen: split by reviewability — layouts committed, data regenerated + golden manifest | Reviewable diffs where they carry meaning; repo stays small; determinism still provable in CI | Two rules for one directory, which must be documented or it looks inconsistent |
| Commit everything under `generated/` | One simple rule; byte-exact recovery of data without running anything | ~900 MB per scale, unusable history, review noise that trains people to ignore diffs |
| Commit nothing under `generated/` | Smallest repo; one simple rule | Loses ADR 001's whole point — the domain children stop being reviewable artifacts and silent split regressions return |
| Commit data to Git LFS or object storage | Keeps bytes recoverable without repo bloat | Reintroduces an external dependency of exactly the kind goal-01 exists to remove (the S3 bucket problem, renamed) |

## Consequences

- **Positive:** a split regression is visible in review; the repo stays clonable; data reproducibility
  is enforced by a determinism test rather than by storage.
- **Negative / trade-offs:** one directory carries two `.gitignore` rules, which is surprising
  without this ADR; recovering a specific past dataset means re-running the generator at the recorded
  seed and scale rather than checking out bytes.
- **Neutral:** the golden manifest must be regenerated deliberately whenever generation rules change,
  and that diff is the signal that they did.

## Revisit Trigger

If the generated layouts ever grow past the point where their diffs stop being read — or if a domain
child's JSON becomes large enough to dominate review — revisit committing them and lean on FEAT-006's
verification plus the manifest approach instead.
