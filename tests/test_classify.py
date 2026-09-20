"""The failure taxonomy, against canned server strings.

Pure function, so every category is testable without a host — which is the only reason a
taxonomy stays honest as it grows. The priority order is asserted explicitly where two rules
could both match, because "first match wins" is only a useful rule if the order is deliberate.
"""

from __future__ import annotations

import pytest

from globalmart.classify import (
    HINTS,
    FailureCategory,
    classify,
    extract_status,
    is_retryable,
)


@pytest.mark.parametrize(
    ("error", "status", "expected"),
    [
        (
            "Bad Request: the filter values for the workspace data filter are empty",
            400,
            FailureCategory.WDF_NO_VALUE,
        ),
        ("Please contact your administrator", 403, FailureCategory.PROTECTED),
        ("ProtectedReportSdkError: restricted", None, FailureCategory.PROTECTED),
        ("429 Too Many Requests", 429, FailureCategory.RATE_LIMITED),
        ("rate limit exceeded", None, FailureCategory.RATE_LIMITED),
        ("xtab-rows limit exceeded", 400, FailureCategory.DATA_LIMIT),
        ("The size of the dimension is too large", 400, FailureCategory.DATA_LIMIT),
        ("The report is too large to compute", 400, FailureCategory.TOO_LARGE_TIMEOUT),
        ("We can't find this visualization", 404, FailureCategory.INVALID_IDENTIFIER),
        ("Object not found", None, FailureCategory.INVALID_IDENTIFIER),
        ("unmapped dataset after schema change", 400, FailureCategory.LDM_MAPPING),
        ("Error while calculating the result", 400, FailureCategory.CALC_ERROR),
        ("general error occurred", 400, FailureCategory.CALC_ERROR),
        ("'properties'", None, FailureCategory.UNSUPPORTED_TYPE),
        ("KeyError: 'properties'", None, FailureCategory.UNSUPPORTED_TYPE),
        ("Internal Server Error", 500, FailureCategory.TRANSIENT_5XX),
        ("Service Unavailable", 503, FailureCategory.TRANSIENT_5XX),
        ("Timeout: did not respond within 180s", None, FailureCategory.TIMEOUT),
        ("something nobody has seen before", None, FailureCategory.UNKNOWN),
    ],
)
def test_categories(error: str, status: int | None, expected: FailureCategory) -> None:
    assert classify(error, status).category is expected


def test_every_category_has_a_hint() -> None:
    """A category without a remediation hint is a label, not a diagnosis."""
    for category in FailureCategory:
        assert HINTS[category].strip()


def test_a_rate_limit_is_not_read_as_a_generic_5xx() -> None:
    """Order matters: the remedy for 429 is to slow down, not to investigate the content."""
    assert classify("Too Many Requests", 429).category is FailureCategory.RATE_LIMITED


def test_wdf_wins_over_calc_error() -> None:
    """The workspace-wide cause must beat the per-object one, or it reads as N defects."""
    both = "General error while calculating: filter values are empty"
    assert classify(both, 400).category is FailureCategory.WDF_NO_VALUE


def test_only_infrastructure_is_retryable() -> None:
    retryable = {category for category in FailureCategory if is_retryable(category)}
    assert retryable == {FailureCategory.TRANSIENT_5XX, FailureCategory.RATE_LIMITED}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("HTTP 500 Server Error", 500),
        ("status: 404 not found", 404),
        ("failed (400)", 400),
        ("Reason: 503", 503),
        ("no status at all", None),
    ],
)
def test_status_extraction_from_text(text: str, expected: int | None) -> None:
    assert extract_status(RuntimeError(text)) == expected


def test_status_attribute_wins_over_the_text() -> None:
    error = RuntimeError("mentions 500 in passing")
    error.status = 429  # type: ignore[attr-defined]
    assert extract_status(error) == 429


def test_a_bool_status_is_ignored() -> None:
    """`bool` is an `int` subclass; `status=True` is not HTTP 1."""
    error = RuntimeError("HTTP 500")
    error.status = True  # type: ignore[attr-defined]
    assert extract_status(error) == 500


def test_empty_error_is_unknown_not_a_crash() -> None:
    assert classify("", None).category is FailureCategory.UNKNOWN
