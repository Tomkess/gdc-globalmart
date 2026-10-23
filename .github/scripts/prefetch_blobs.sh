#!/usr/bin/env bash
#
# Fetch, in one request, the file contents a partial (blob:none) clone lacks
# for <path>... at <ref>. git's own lazy fetch splits them into dozens of
# round trips: restoring one data product from an old tag took 55 s that way
# and 1.7 s through this. A no-op in a full clone.
#
# Usage: prefetch_blobs.sh <ref> <path>...

set -euo pipefail

if (( $# < 2 )); then
  echo "Usage: prefetch_blobs.sh <ref> <path>..." >&2
  exit 2
fi
ref="$1"
shift

missing="$(git ls-tree -r --format='%(objecttype) %(objectname)' "$ref" -- "$@" \
  | sed -n 's/^blob //p' \
  | GIT_NO_LAZY_FETCH=1 git cat-file --batch-check='%(objectname)' \
  | sed -n 's/ missing$//p')"

if [[ -n "$missing" ]]; then
  echo "📥 Fetching $(wc -l <<<"$missing" | tr -d ' ') file(s) at $ref" >&2
  git -c fetch.negotiationAlgorithm=noop fetch --quiet --no-tags \
    --no-write-fetch-head --recurse-submodules=no --filter=blob:none \
    origin --stdin <<<"$missing"
fi
