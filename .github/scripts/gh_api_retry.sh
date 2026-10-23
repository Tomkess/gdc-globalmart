#!/usr/bin/env bash
#
# Run `gh api "$@"` with bounded retries, for the calls that have no local
# equivalent (a run's job statuses, say — that state lives only server-side).
# Anything answerable from the checkout uses pr_changed_files.sh instead. `gh`
# has no --retry flag, so retry lives here.
#
# Retries on ANY non-zero exit rather than pattern-matching stderr: a 404 or a
# bad token fails identically on every attempt, costing the backoff and no
# correctness, whereas a transient-vs-fatal pattern rots as gh's error strings
# change.
#
# Each attempt is BUFFERED and emitted only on success, because `gh api` writes
# the HTTP error body to *stdout* and `--jq` does not filter it:
#
#   $ gh api repos/o/r/pulls/99999999 --jq '.[].name'
#   {"message":"Not Found","documentation_url":"…","status":"404"}
#
# Streaming would hand the caller that JSON as data, and failure-then-success
# would splice it onto valid results. Cost: no streaming of a large --paginate
# response, which nothing here relies on.
#
# stdout stays clean for the caller to capture — progress goes to stderr. After
# ATTEMPTS failures it exits with the last attempt's status, so callers keep
# their fail-closed behaviour.
#
# Usage: gh_api_retry.sh <gh api args...>
# Tunables (env): GH_API_ATTEMPTS (default 4), GH_API_BACKOFF (default 3s,
# doubling) — 3s + 6s + 12s ≈ 21s worst case, well inside a gate's budget.

set -euo pipefail

attempts="${GH_API_ATTEMPTS:-4}"
backoff="${GH_API_BACKOFF:-3}"

# A non-positive or non-numeric `attempts` skips the loop entirely, leaving
# `status` unset for the final error line — under `set -u` that aborts with
# "status: unbound variable" instead of naming the real problem.
if ! [[ "$attempts" =~ ^[1-9][0-9]*$ && "$backoff" =~ ^[1-9][0-9]*$ ]]; then
  echo "::error::GH_API_ATTEMPTS (${attempts}) and GH_API_BACKOFF (${backoff}) must be positive integers" >&2
  exit 1
fi

for ((attempt = 1; attempt <= attempts; attempt++)); do
  status=0
  output=$(gh api "$@") || status=$?

  if [[ "$status" -eq 0 ]]; then
    # Guard the empty case: `printf '%s\n' ""` would emit a lone newline where
    # the API legitimately returned nothing.
    if [[ -n "$output" ]]; then
      printf '%s\n' "$output"
    fi
    exit 0
  fi

  if [[ "$attempt" -lt "$attempts" ]]; then
    echo "::warning::gh api failed (exit ${status}), attempt ${attempt}/${attempts} — retrying in ${backoff}s" >&2
    sleep "$backoff"
    backoff=$((backoff * 2))
  fi
done

echo "::error::gh api failed after ${attempts} attempts (last exit ${status}): gh api $*" >&2
# The buffered body is the actual cause ({"message":"Not Found",...}); without
# this the caller sees only an exit code. To stderr, so stdout stays clean and
# the fail-closed contract above is unchanged.
if [[ -n "${output:-}" ]]; then
  echo "::error::last response body: ${output}" >&2
fi
exit "$status"
