"""The failure taxonomy: what a server error actually means, and what to do about it.

Ported from the predecessor's `Misc/scripts/classifier.py`, which earned its keep over 13
workspaces. Kept pure — no network, no SDK import — so every category is unit-testable with
a canned string, which is the only way a taxonomy stays honest.

**The categories are matched in priority order and the first match wins.** That order is not
arbitrary: `WDF_NO_VALUE` is first because it is the one failure that hits *every*
visualization in a workspace at once, and reading it as N separate defects is exactly the
misdiagnosis this module exists to prevent.

Two categories are added to the predecessor's eleven:

- `EMPTY_RESULT` — the execution succeeded and returned nothing. Not a failure by default,
  because GlobalMart has legitimately empty slices, but never folded into `OK` either: an
  unloaded warehouse would otherwise pass the whole goal-01 claim silently.
- `RATE_LIMITED` — a 429. Retried like a 5xx, but distinguished from it, because the remedy
  is to slow down rather than to investigate the content.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import NamedTuple


class FailureCategory(StrEnum):
    WDF_NO_VALUE = "WDF_NO_VALUE"
    PROTECTED = "PROTECTED"
    INVALID_IDENTIFIER = "INVALID_IDENTIFIER"
    LDM_MAPPING = "LDM_MAPPING"
    DATA_LIMIT = "DATA_LIMIT"
    CALC_ERROR = "CALC_ERROR"
    TOO_LARGE_TIMEOUT = "TOO_LARGE_TIMEOUT"
    TRANSIENT_5XX = "TRANSIENT_5XX"
    RATE_LIMITED = "RATE_LIMITED"
    UNSUPPORTED_TYPE = "UNSUPPORTED_TYPE"
    TIMEOUT = "TIMEOUT"
    EMPTY_RESULT = "EMPTY_RESULT"
    UNKNOWN = "UNKNOWN"


HINTS: dict[FailureCategory, str] = {
    FailureCategory.WDF_NO_VALUE: (
        "Workspace data filter is defined but has no value set — set a filter value. "
        "This fails every visualization in the workspace at once; the WDF preflight "
        "reports it above the per-object list."
    ),
    FailureCategory.PROTECTED: (
        "Restricted by access/security rules — check the user's data-access permissions "
        "on the workspace."
    ),
    FailureCategory.INVALID_IDENTIFIER: (
        "Dangling or renamed identifier — inspect the visualization definition and fix or "
        "remove the bad attribute/label/filter id. In a repo-built org this usually means "
        "the split dropped something the visualization still references."
    ),
    FailureCategory.LDM_MAPPING: (
        "LDM mapping warning after a schema change — review the LDM mapping and re-sync "
        "the datasets."
    ),
    FailureCategory.DATA_LIMIT: (
        "Dimension exceeds the row limit (default 10k) — add a metric or a filter to "
        "reduce cardinality."
    ),
    FailureCategory.CALC_ERROR: (
        "SQL or calculation error — verify the data source's permissions and that the "
        "warehouse schema actually holds the tables the LDM points at."
    ),
    FailureCategory.TOO_LARGE_TIMEOUT: (
        "Unbounded date range — narrow the date filter (avoid 'All Time')."
    ),
    FailureCategory.TRANSIENT_5XX: (
        "Intermittent infrastructure failure — retried automatically; not a deterministic "
        "visualization defect."
    ),
    FailureCategory.RATE_LIMITED: (
        "The host is rate limiting — the run halves its concurrency and retries. Lower "
        "--max-workers if this recurs."
    ),
    FailureCategory.UNSUPPORTED_TYPE: (
        "for_visualization() does not support this visualization type (e.g. local:table). "
        "Recorded as SKIPPED, not broken, and counted separately so the 'every "
        "visualization' claim is not quietly narrowed."
    ),
    FailureCategory.TIMEOUT: (
        "Execution hung past the per-visualization timeout — investigate query complexity. "
        "Treated as broken."
    ),
    FailureCategory.EMPTY_RESULT: (
        "Executed successfully and returned zero rows. Often legitimate; if most of a "
        "workspace is empty the warehouse is probably unloaded or the schema is wrong."
    ),
    FailureCategory.UNKNOWN: (
        "Unrecognised error — inspect the raw error and the visualization definition by hand."
    ),
}


class Failure(NamedTuple):
    category: FailureCategory
    hint: str


def _as(category: FailureCategory) -> Failure:
    return Failure(category=category, hint=HINTS[category])


def classify(error: str, status: int | None = None) -> Failure:
    """Map a raw error plus optional HTTP status onto a category and a remediation hint."""
    lowered = (error or "").lower()
    stripped = (error or "").strip()

    # 1. A workspace-wide fault, so it must not be diagnosed as N object faults.
    if "filter values" in lowered and "empty" in lowered:
        return _as(FailureCategory.WDF_NO_VALUE)
    # 2. Access or security restriction.
    if "contact your administrator" in lowered or "protectedreportsdkerror" in lowered:
        return _as(FailureCategory.PROTECTED)
    # 3. Rate limiting — checked before the generic 5xx so the remedy is the right one.
    if status == 429 or "too many requests" in lowered or "rate limit" in lowered:
        return _as(FailureCategory.RATE_LIMITED)
    # 4. Dimension row-limit exceeded.
    if "xtab-rows" in lowered or "size of the dimension" in lowered:
        return _as(FailureCategory.DATA_LIMIT)
    # 5. Unbounded date range / report too large.
    if "report is too large" in lowered or "all time" in lowered:
        return _as(FailureCategory.TOO_LARGE_TIMEOUT)
    # 6. Dangling or renamed identifier, or a missing object.
    if (
        "can't find this visualization" in lowered
        or "not found" in lowered
        or status == 404
    ):
        return _as(FailureCategory.INVALID_IDENTIFIER)
    # 7. LDM mapping warning after a schema change.
    if "unmapped" in lowered or "mapping" in lowered:
        return _as(FailureCategory.LDM_MAPPING)
    # 8. SQL or calculation error, typically HTTP 400.
    if (
        "while calculating" in lowered
        or "calculating the result" in lowered
        or "general error" in lowered
    ):
        return _as(FailureCategory.CALC_ERROR)
    # 9. for_visualization() on an unsupported type raises a bare KeyError('properties').
    if stripped in ("'properties'", '"properties"') or "keyerror: 'properties'" in lowered:
        return _as(FailureCategory.UNSUPPORTED_TYPE)
    # 10. Transient infrastructure failure.
    if status is not None and 500 <= status <= 599:
        return _as(FailureCategory.TRANSIENT_5XX)
    # 11. The per-visualization timeout sentinel.
    if "timeout" in lowered:
        return _as(FailureCategory.TIMEOUT)
    return _as(FailureCategory.UNKNOWN)


#: An HTTP status embedded in an exception string: "HTTP 500", "status: 404", "(400)",
#: "Reason: 503".
_STATUS_RE = re.compile(r"(?:http[\s_/]*|status[:\s]*|reason[:\s]*|\()(\d{3})\b", re.IGNORECASE)


def extract_status(exc: BaseException) -> int | None:
    """Best-effort HTTP status: the exception's own attribute, else a regex over its text."""
    status = getattr(exc, "status", None)
    if isinstance(status, bool):  # bool is an int subclass — not a status
        status = None
    if isinstance(status, int):
        return status
    if isinstance(status, str) and status.isdigit():
        return int(status)
    match = _STATUS_RE.search(str(exc))
    return int(match.group(1)) if match else None


def is_retryable(category: FailureCategory) -> bool:
    """Only infrastructure noise is retried.

    Retrying a deterministic failure would turn a real defect into a slow real defect, and
    retrying enough times would eventually let a flaky pass hide it.
    """
    return category in (FailureCategory.TRANSIENT_5XX, FailureCategory.RATE_LIMITED)
