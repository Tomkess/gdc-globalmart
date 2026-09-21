"""Reading GoodData DataParts — the chart definition and the rows that go with it.

A workspace answers with two artifacts per chart: a **`visualization`** carrying the agent's
own chart type, title and query, and a **`visualization-data`** carrying columns, rows and
`formattedRows`, paired by `visualizationId`. They are GoodData-specific and protocol-neutral
— an MCP lane returns the same shapes — so reading them lives here rather than in
`a2a/client.py`, and both the lane and the orchestrator's alignment use the same rules.

Nothing here interprets an answer. It resolves names, grains and windows that the agent
already stated, and hands them on.
"""

from __future__ import annotations

import re
from typing import Any

#: `{metric/metric_l1_total_campaign_spend}` as the agent writes it mid-sentence.
PLACEHOLDER = re.compile(r"\{(metric|fact|attribute|label|dataset)/([^}]+)\}")


def data_of(artifact: Any) -> dict[str, Any] | None:
    data = artifact.get("data") if isinstance(artifact, dict) else None
    return data if isinstance(data, dict) else None


def chart_pairs(artifacts: Any) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    """Each `visualization` with the `visualization-data` that belongs to it.

    Paired by `visualizationId` rather than by position, because a lane can return several
    charts and their order is the agent's, not ours. A definition with no rows still comes
    back — it is an answer that returned nothing, which is different from no answer.
    """
    definitions = [
        d for a in artifacts or () if (d := data_of(a)) and a.get("name") == "visualization"
    ]
    rows = [
        d for a in artifacts or () if (d := data_of(a)) and a.get("name") == "visualization-data"
    ]
    by_id = {str(d.get("visualizationId")): d for d in rows if d.get("visualizationId")}

    pairs: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for index, definition in enumerate(definitions):
        match = by_id.get(str(definition.get("id")))
        if match is None and len(definitions) == 1 and len(rows) == 1:
            # One of each and no id to match on: they can only belong together.
            match = rows[0]
        elif match is None and index < len(rows) and not by_id:
            match = rows[index]
        pairs.append((definition, match))
    return pairs


def _using(visualization: dict[str, Any], key: str) -> str:
    fields = (visualization.get("query") or {}).get("fields") or {}
    entry = fields.get(key) or {}
    return str(entry.get("using") or key)


def grain_of(visualization: dict[str, Any]) -> str | None:
    """What the chart is broken down by, as two lanes would have to agree on it.

    `label/transaction_date.month` -> `month`: the part after the last dot is the
    granularity. A chart broken down by two attributes reports both, joined — it is one
    grain made of two parts, not two grains.
    """
    parts: list[str] = []
    for key in visualization.get("view_by") or []:
        reference = _using(visualization, str(key))
        parts.append(reference.rsplit(".", 1)[-1] if "." in reference else reference.split("/")[-1])
    return ", ".join(parts) or None


def window_of(visualization: dict[str, Any]) -> str | None:
    """The period, kept in whatever form the agent expressed it.

    Relative bounds stay relative. Two lanes both saying `-5..0 MONTH` agree; resolving them
    to absolute dates would invent a precision the agent never claimed.
    """
    for spec in ((visualization.get("query") or {}).get("filter_by") or {}).values():
        if isinstance(spec, dict) and spec.get("type") == "date_filter":
            granularity = str(spec.get("granularity") or "")
            return f"{spec.get('from')}..{spec.get('to')} {granularity}".strip()
    return None


def filters_of(visualization: dict[str, Any]) -> list[str]:
    """Non-date filters, so `filter_parity` has something to compare."""
    found = []
    for name, spec in ((visualization.get("query") or {}).get("filter_by") or {}).items():
        if isinstance(spec, dict) and spec.get("type") != "date_filter":
            found.append(f"{name}={spec.get('type') or 'filter'}")
    return found


def columns_of(data: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """Attribute column names and metric column names, in the order the rows use them."""
    columns = (data or {}).get("columns") or []
    attributes = [str(c.get("name")) for c in columns if isinstance(c, dict) and c.get("type") == "attribute"]
    metrics = [str(c.get("name")) for c in columns if isinstance(c, dict) and c.get("type") != "attribute"]
    return attributes, metrics


def label_map(artifacts: Any) -> dict[str, str]:
    """`metric/metric_l1_total_campaign_spend` -> `Total Campaign Spend`.

    The agent writes object *ids* into its prose — "`{metric/metric_l1_total_campaign_spend}`
    did not have a campaign breakdown available" — while the very same response carries the
    human label in the data artifact's columns. The mapping is positional and stated by the
    agent itself: `view_by` in order against the attribute columns, `metrics` in order
    against the metric columns.

    So this resolves a name the agent already gave; it does not invent one. Where no mapping
    exists the placeholder is left exactly as written, because a plausible-looking label
    derived from an identifier would be a guess presented as a fact.
    """
    labels: dict[str, str] = {}
    for visualization, data in chart_pairs(artifacts):
        attribute_names, metric_names = columns_of(data)
        for keys, names in (
            (visualization.get("view_by") or [], attribute_names),
            (visualization.get("metrics") or [], metric_names),
        ):
            for key, name in zip(keys, names, strict=False):
                reference = _using(visualization, str(key))
                if reference and name:
                    labels.setdefault(reference, name)
    return labels


def resolve_placeholders(text: str, labels: dict[str, str]) -> str:
    """Swap object ids for the labels the same response carried. Leave the rest alone."""
    if not text:
        return text

    def swap(match: re.Match[str]) -> str:
        reference = f"{match.group(1)}/{match.group(2)}"
        return labels.get(reference, match.group(0))

    return PLACEHOLDER.sub(swap, text)


def unresolved(text: str) -> tuple[str, ...]:
    """Ids still showing in prose after resolution — a gap-list item, not a rendering bug."""
    return tuple(dict.fromkeys(m.group(0) for m in PLACEHOLDER.finditer(text or "")))
