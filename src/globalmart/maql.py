"""The one module that knows MAQL reference syntax.

A metric's `maql` is a string like::

    SELECT AVG({fact/fact_daily_store_sales.sales_amount}) WHERE {label/transaction_date.month} = 1

and the ids inside those braces are what decides whether a child workspace loads. The
predecessor extracted only `{metric/...}` with a one-line `re.findall`; that single pattern
is the reason its children loaded at all, and the reason they could not compute — every
`{fact/...}` and `{label/...}` dependency was invisible to it, so the datasets owning them
were never retained.

**On the dot.** A bare id may contain dots, and the dot means two different things:

    {fact/fact_daily_store_sales.sales_amount}   -> id is the whole dotted string
    {label/transaction_date.month}               -> id is `transaction_date`, granularity `month`

Nothing in the syntax distinguishes them — `transaction_date` is a date instance and
`fact_daily_store_sales` is a dataset, and only the LDM knows which. So this module does
**not** guess: it captures the whole dotted string as the id and leaves the split to
`prune.EntityIndex.resolve_entity`, which can check it against the date instances that
actually exist. A regex that treats every dot as a granularity separator silently truncates
every fact and attribute id in the parent; one that treats no dot as a separator fails to
resolve every date reference. Neither is recoverable downstream, which is why the decision
lives where the information is.

Verified against the committed parent: 1807 `{metric/}`, 968 `{label/}` and 132 `{fact/}`
references across 1091 metrics, all of which resolve (`tests/test_maql.py`).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from enum import StrEnum
from typing import NamedTuple


class RefKind(StrEnum):
    """What an id inside a reference points at."""

    METRIC = "metric"
    FACT = "fact"
    ATTRIBUTE = "attribute"
    LABEL = "label"
    DATASET = "dataset"
    DATE_INSTANCE = "dateInstance"


#: The one pattern. Bare ids keep their dots — see the module docstring.
MAQL_REF_RE = re.compile(
    r"\{(?P<kind>metric|fact|attribute|label|dataset)/"
    r'(?:"(?P<quoted>[^"]+)"|(?P<bare>[^}]+))'
    r"\}"
)


class MaqlRef(NamedTuple):
    """One reference found in a MAQL string."""

    kind: RefKind
    id: str

    @property
    def base(self) -> str:
        """The id up to the first dot — a date instance id when this is a date reference."""
        return self.id.split(".", 1)[0]

    @property
    def suffix(self) -> str | None:
        """Everything after the first dot, or ``None``. A granularity, when it is one."""
        _, _, rest = self.id.partition(".")
        return rest or None


def iter_maql_refs(maql: str | None) -> Iterator[MaqlRef]:
    """Yield every reference in a MAQL string, in source order, duplicates included.

    Callers deduplicate if they care; the closure works on sets anyway, and keeping
    duplicates here means a caller counting references gets a true count.
    """
    if not maql:
        return
    for match in MAQL_REF_RE.finditer(maql):
        identifier = match.group("quoted") or match.group("bare")
        yield MaqlRef(kind=RefKind(match.group("kind")), id=identifier.strip())


def maql_metric_ids(maql: str | None) -> set[str]:
    """Just the `{metric/...}` ids — the transitive closure's worklist input."""
    return {ref.id for ref in iter_maql_refs(maql) if ref.kind is RefKind.METRIC}
