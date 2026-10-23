#!/usr/bin/env bash
#
# Print the PR's changed file paths, one per line, resolved from the local
# clone — the single source of truth for "what did this PR touch" across CI.
# Why git rather than `gh api .../pulls/<N>/files`: see AGENTS.md, "Never call
# `gh api` for the PR's file list" (fail-closed gate + silent 3000-file cap).
#
# Contract: three-dot diff against the PR's base. On `pull_request` events the
# checkout is the merge commit, so `origin/<base>...HEAD` is exactly the PR
# diff — the same range gd-validate precommit uses locally, keeping local and CI
# byte-for-byte identical on the changed-file set.
#
# Requires the caller's actions/checkout to set `fetch-depth: 0` and
# `filter: blob:none` (blobless keeps that ~1s). Both guards below exit
# non-zero with an actionable ::error:: rather than printing an empty list —
# empty is indistinguishable from "touched nothing" and would let a gate pass
# having validated nothing.

set -euo pipefail

# After a merge `origin/<base>...HEAD` is empty; the caller passes the PR's own
# commits instead, which works whichever way it was merged.
if [[ -n "${PR_BASE_SHA:-}" || -n "${PR_HEAD_SHA:-}" ]]; then
  for sha in "${PR_BASE_SHA:-}" "${PR_HEAD_SHA:-}"; do
    if [[ -z "$sha" ]] || ! git cat-file -e "${sha}^{commit}" 2>/dev/null; then
      echo "::error::PR commit '${sha}' not in local clone — set both PR_BASE_SHA and PR_HEAD_SHA, and check out with 'fetch-depth: 0'." >&2
      exit 1
    fi
  done
  git -c core.quotePath=false diff --name-only "${PR_BASE_SHA}...${PR_HEAD_SHA}"
  exit 0
fi

if [[ -z "${GITHUB_BASE_REF:-}" ]]; then
  echo "::error::GITHUB_BASE_REF is empty — resolving PR changed files requires a pull_request event" >&2
  exit 1
fi

if ! git rev-parse --verify "origin/${GITHUB_BASE_REF}" >/dev/null 2>&1; then
  echo "::error::origin/${GITHUB_BASE_REF} not in local clone — cannot diff against the PR base." >&2
  echo "::error::Add 'fetch-depth: 0' and 'filter: blob:none' to the caller's actions/checkout step." >&2
  exit 1
fi

# quotePath=false so a non-ASCII path is printed literally rather than escaped
# and double-quoted — the escaped form matches neither the caller's `grep -E`
# patterns nor `gd-detect-dp`, and it silently depends on the runner's git config.
git -c core.quotePath=false diff --name-only "origin/${GITHUB_BASE_REF}...HEAD"
