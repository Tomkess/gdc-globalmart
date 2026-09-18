# 002 — Publishing requires an explicit `--apply`

**Status:** Accepted
**Date:** 2026-09-18
**Context:** feat-002 (publish parent), feat-004 (publish domain workspaces), any future command that
writes to a GoodData org

## Decision

Every command that writes to a live GoodData org is a read-only rehearsal by default and performs
writes only when `--apply` is passed. The rehearsal runs the entire pipeline — preflight, datasource
resolution, placeholder substitution, `assert_fully_resolved`, backup, diff — and stops at the three
write calls. In addition, a backup of the target workspace's current layout is taken immediately
before the PUT whenever writes are enabled, and `--no-backup` is refused unless `--apply` is also
present.

The driver is `put_declarative_workspace`, which has REPLACE semantics: it overwrites a workspace's
entire content in one call. The targets in play are real — `petertomko.demo.cloud` and the
local-inference host — and an API token is often scoped more broadly than the workspace being
published. A mistyped profile name with a write-by-default CLI silently destroys a workspace, and
the layout it replaced exists nowhere else.

## Alternatives Considered

| Option | Pros | Cons |
|---|---|---|
| Chosen: rehearsal by default, `--apply` to write | Impossible to destroy a workspace with a typo or a wrong `--target`; the diff is always seen before it is applied; matches `terraform plan`/`apply`, which the user already works in | Two invocations for every real publish; scripts and CI must remember the flag |
| Write by default, `--dry-run` to preview | One command, conventional for build tooling | The dangerous path is the one you get by accident; the spec's own risk table rated this High/High |
| Write by default, interactive confirmation prompt | Ergonomic for humans | Breaks non-interactive use (CI, agents); prompts get muscle-memoried away; an agent cannot answer one |
| Write by default with automatic backup only | No flag to remember | Backup is a recovery path, not a prevention; restoring 2.9 MB of layout into a live org is itself a risky operation |

## Consequences

- **Positive:** the destructive path is opt-in and explicit; every publish is preceded by a diff the
  operator has actually seen; the same gate protects FEAT-004's 12 child publishes, where a mistake
  would be 12× worse; an agent running the command without the flag cannot do damage.
- **Negative / trade-offs:** every real publish is two commands; documentation and any future CI job
  must carry `--apply` explicitly; a test must pin the default so it cannot be flipped silently.
- **Neutral:** the rehearsal still performs reads against the host (org identity check, existing
  layout fetch for the backup and diff), so it is not an offline operation and still needs
  credentials.

## Revisit Trigger

If publishing becomes a frequent, low-stakes operation against throwaway orgs — for example a CI job
that rebuilds a scratch org on every merge — add a per-profile `require_apply: false` opt-out in
`config/targets.yaml` for those targets only, rather than changing the global default. Targets that
hold anything a human would miss keep the gate.
