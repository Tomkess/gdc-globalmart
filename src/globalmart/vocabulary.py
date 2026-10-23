"""Realistic values for generated text columns, read from `config/vocabulary.yaml` (FEAT-021).

The generator names a text column after itself plus a row index (`City Name 0005`), because it
names no table and no column: a table added to the DDL generates without an edit. That property
stays. What a column should *say* is a fact about the demo, not about the schema, so it lives here
as data — config, not code (STEERING) — and a column the file does not mention is untouched.

Five kinds of rule, each per table:

``records``    one record per row, in row order: several columns that belong together
               (`USD` + `US Dollar` + its rate), plus ``ref`` pins that choose a foreign key by
               the referenced row's value (a country's currency is the one whose code is `USD`).
``by_parent``  a name chosen within the referenced row's subtree: a region of *its* country, a
               city of *its* region. This is what keeps names coherent with the geography.
``template``   a value built from this row and the rows it references (`GlobalMart {city_id.city_name}`).
``compose``    a name built from word lists, without repeats (first names x surnames).
``choose``     a value picked from a list; repeats allowed (a store format).

Names in ``records``, ``by_parent``, ``template`` and ``compose`` are distinct within their column:
if a list runs out, a deterministic suffix (`Boston 2`) keeps them apart.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from globalmart.config import GlobalmartError

DEFAULT_VOCABULARY_PATH = Path("config/vocabulary.yaml")

_TABLE_KEYS = frozenset({"records", "by_parent", "template", "compose", "choose"})
_BY_PARENT_KEYS = frozenset({"column", "via", "key", "values"})

#: `(foreign-key column, referenced column) -> referenced row's value`, for this row.
ParentLookup = Callable[[str, str], str]


class VocabularyError(GlobalmartError):
    """`config/vocabulary.yaml` does not describe a vocabulary this module can apply."""


@dataclass(frozen=True)
class ByParent:
    column: str  # the column being named, e.g. `city_name`
    via: str  # the foreign key selecting the parent, e.g. `region_id`
    key: str  # the parent's column to look up, e.g. `region_name`
    values: dict[str, tuple[str, ...]]  # parent value -> names in that subtree


@dataclass(frozen=True)
class TableVocabulary:
    table: str
    records: tuple[dict[str, str], ...] = ()
    refs: tuple[dict[str, dict[str, str]], ...] = ()  # per record: fk column -> {column: value}
    by_parent: tuple[ByParent, ...] = ()
    template: dict[str, str] = field(default_factory=dict)
    compose: dict[str, tuple[tuple[str, ...], ...]] = field(default_factory=dict)
    choose: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def columns(self) -> frozenset[str]:
        """Every column this table's rules write."""
        written = {c for record in self.records for c in record}
        written |= {rule.column for rule in self.by_parent}
        return frozenset(written | set(self.template) | set(self.compose) | set(self.choose))


@dataclass(frozen=True)
class Vocabulary:
    tables: dict[str, TableVocabulary]
    path: Path | None = None

    def for_table(self, name: str) -> TableVocabulary | None:
        return self.tables.get(name)


def load_vocabulary(path: Path = DEFAULT_VOCABULARY_PATH) -> Vocabulary | None:
    """The vocabulary, or ``None`` when the file does not exist (generation is then unchanged)."""
    if not path.exists():
        return None
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if document.get("version") != 1:
        raise VocabularyError(f"{path}: expected `version: 1`")
    tables: dict[str, TableVocabulary] = {}
    for name, spec in (document.get("tables") or {}).items():
        tables[name] = _parse_table(path, name, spec or {})
    return Vocabulary(tables=tables, path=path)


def _parse_table(path: Path, name: str, spec: Mapping[str, Any]) -> TableVocabulary:
    unknown = set(spec) - _TABLE_KEYS
    if unknown:
        raise VocabularyError(f"{path}: {name}: unknown key(s) {sorted(unknown)}")

    records: list[dict[str, str]] = []
    refs: list[dict[str, dict[str, str]]] = []
    for record in spec.get("records") or []:
        record = dict(record)
        ref = record.pop("ref", None) or {}
        records.append({column: str(value) for column, value in record.items()})
        refs.append({fk: {str(k): str(v) for k, v in pin.items()} for fk, pin in ref.items()})

    by_parent = []
    for rule in spec.get("by_parent") or []:
        missing = _BY_PARENT_KEYS - set(rule)
        if missing:
            raise VocabularyError(f"{path}: {name}: by_parent rule lacks {sorted(missing)}")
        by_parent.append(
            ByParent(
                column=str(rule["column"]),
                via=str(rule["via"]),
                key=str(rule["key"]),
                values={str(k): tuple(str(v) for v in vs) for k, vs in (rule["values"] or {}).items()},
            )
        )

    compose = {
        column: tuple(tuple(str(word) for word in words) for words in lists)
        for column, lists in (spec.get("compose") or {}).items()
    }
    for column, lists in compose.items():
        if len(lists) < 2 or not all(lists):
            raise VocabularyError(f"{path}: {name}.{column}: compose needs two or more non-empty lists")

    return TableVocabulary(
        table=name,
        records=tuple(records),
        refs=tuple(refs),
        by_parent=tuple(by_parent),
        template={str(c): str(t) for c, t in (spec.get("template") or {}).items()},
        compose=compose,
        choose={str(c): tuple(str(v) for v in vs) for c, vs in (spec.get("choose") or {}).items()},
    )


# --- resolution ---------------------------------------------------------------


def stable_index(key: str, size: int) -> int:
    """A deterministic index in `[0, size)`. blake2b, because `hash()` is salted per process."""
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % size


def composed(lists: tuple[tuple[str, ...], ...], index: int) -> str:
    """The `index`-th distinct combination, scattered so neighbours do not share a first word.

    A step coprime with the number of combinations walks every one exactly once before any
    repeats, so the first `math.prod(len(list))` rows are all distinct.
    """
    total = math.prod(len(words) for words in lists)
    step = next(p for p in range(7919, 7919 + total + 2) if math.gcd(p, total) == 1)
    position = (index * step) % total
    words = []
    for word_list in lists:
        position, offset = divmod(position, len(word_list))
        words.append(word_list[offset])
    return " ".join(words)


@dataclass
class TableNamer:
    """Applies one table's vocabulary row by row, keeping names distinct within a column."""

    vocabulary: TableVocabulary
    used: dict[str, set[str]] = field(default_factory=dict)
    per_parent: dict[tuple[str, str], int] = field(default_factory=dict)

    def pins(self, index: int) -> dict[str, dict[str, str]]:
        """Foreign keys this row must point at, chosen by the referenced row's values."""
        refs = self.vocabulary.refs
        return refs[index % len(refs)] if refs else {}

    def apply(self, index: int, values: dict[str, str], parent: ParentLookup) -> None:
        """Overwrite this row's vocabulary columns in place."""
        vocab = self.vocabulary
        if vocab.records:
            record = vocab.records[index % len(vocab.records)]
            for column, value in record.items():
                values[column] = self._distinct(column, value) if column in self._name_columns() else value

        for rule in vocab.by_parent:
            parent_value = parent(rule.via, rule.key)
            names = rule.values.get(parent_value)
            if not names:
                continue
            slot = self.per_parent.get((rule.column, parent_value), 0)
            self.per_parent[(rule.column, parent_value)] = slot + 1
            values[rule.column] = self._distinct(rule.column, names[slot % len(names)])

        for column, lists in vocab.compose.items():
            values[column] = self._distinct(column, composed(lists, index))

        for column, choices in vocab.choose.items():
            values[column] = choices[stable_index(f"{vocab.table}.{column}:{index}", len(choices))]

        for column, pattern in vocab.template.items():
            values[column] = self._distinct(column, _render(pattern, values, parent))

    def _name_columns(self) -> frozenset[str]:
        # In a record, a column whose values are all distinct is an identity (a name or a code),
        # and stays distinct if the records cycle. A repeated value (a rate) is left alone.
        names = set()
        for column in {c for r in self.vocabulary.records for c in r}:
            column_values = [r[column] for r in self.vocabulary.records if column in r]
            if len(set(column_values)) == len(column_values):
                names.add(column)
        return frozenset(names)

    def _distinct(self, column: str, value: str) -> str:
        seen = self.used.setdefault(column, set())
        candidate, suffix = value, 2
        while candidate in seen:
            candidate, suffix = f"{value} {suffix}", suffix + 1
        seen.add(candidate)
        return candidate


def _render(pattern: str, values: Mapping[str, str], parent: ParentLookup) -> str:
    """`{column}` from this row, `{fk_column.column}` from the row the foreign key points at."""
    out, rest = [], pattern
    while "{" in rest:
        before, _, after = rest.partition("{")
        token, _, rest = after.partition("}")
        out.append(before)
        if "." in token:
            fk, _, column = token.partition(".")
            out.append(parent(fk, column))
        else:
            out.append(values.get(token, ""))
    out.append(rest)
    return " ".join("".join(out).split())
