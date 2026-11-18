"""Comparing an extraction with reference data someone else produced.

The reference is plain data shaped like the extraction's `data`: the values a person typed in,
an accounting system's export, last year's report. Every leaf of the reference is checked
against the extracted value at the same path, so the reference decides what is compared.

    checks = compare(extraction, {"total": {"amount": "627.00", "currency": "GBP"}},
                     rules={"*/amount": {"tolerance": "0.01"}})

Numbers compare as decimals, within an absolute or relative tolerance. Text compares exactly,
or ignoring case and spacing. A value that was not extracted is never a match or a mismatch:
it is reported as `not_extracted`, so a missing value cannot pass as agreement.
"""

import fnmatch
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from janus_pdf.document import Anchor
from janus_pdf.extract import Extraction, FieldResult

CheckStatus = Literal["match", "mismatch", "not_extracted"]
TextMode = Literal["exact", "casefold", "spacing"]


@dataclass(frozen=True, slots=True)
class Rule:
    """How to compare the leaves a path pattern matches."""

    tolerance: Decimal = Decimal(0)
    relative: bool = False  # tolerance is a fraction of the reference value
    text: TextMode = "exact"


@dataclass(frozen=True, slots=True)
class Check:
    """One reference leaf compared with the extracted value at the same path."""

    path: str
    status: CheckStatus
    expected: Any
    actual: Any
    message: str = ""
    anchor: Anchor | None = None  # where the extracted value is printed


def rule(raw: Mapping[str, Any] | Rule) -> Rule:
    """A rule from a mapping such as {tolerance: 0.01, relative: false, text: casefold}."""
    if isinstance(raw, Rule):
        return raw
    unknown = set(raw) - {"tolerance", "relative", "text"}
    if unknown:
        raise ValueError(f"unknown rule option(s): {', '.join(sorted(unknown))}")
    return Rule(
        Decimal(str(raw.get("tolerance", 0))),
        bool(raw.get("relative", False)),
        raw.get("text", "exact"),
    )


def _leaves(value: Any, path: str = ""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _leaves(v, f"{path}/{k}" if path else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _leaves(v, f"{path}/{i}" if path else str(i))
    else:
        yield path, value


def _at(data: Any, path: str) -> tuple[bool, Any]:
    for part in path.split("/"):
        if isinstance(data, dict) and part in data:
            data = data[part]
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return False, None
    return True, data


def _owner(results: dict[str, FieldResult], path: str) -> FieldResult | None:
    """The field result a leaf belongs to: the longest result path that prefixes it."""
    parts = path.split("/")
    for n in range(len(parts), 0, -1):
        r = results.get("/".join(parts[:n]))
        if r is not None:
            return r
    return None


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _numeric(actual: Any) -> Decimal | None:
    """An extracted number: an int, or a decimal string as Janus writes them ("627.00").
    Text that happens to be digits, such as an invoice number "0451", is not a number."""
    if isinstance(actual, int) and not isinstance(actual, bool):
        return Decimal(actual)
    if isinstance(actual, str):
        d = _number(actual)
        if d is not None and format(d, "f") == actual:
            return d
    return None


def _text(value: str, mode: TextMode) -> str:
    if mode == "exact":
        return value
    value = " ".join(value.split())
    return value.casefold() if mode == "casefold" else value


def compare(
    extraction: Extraction,
    reference: dict[str, Any],
    rules: Mapping[str, Mapping[str, Any] | Rule] | None = None,
) -> tuple[Check, ...]:
    """One check per leaf of `reference`. `rules` maps path patterns ("total/amount",
    "lines/*/amount/amount", "*") to options; the first pattern that matches applies."""
    patterns = [(p, rule(r)) for p, r in (rules or {}).items()]
    results = {r.path: r for r in extraction.fields}
    data = extraction.data
    checks = []
    for path, expected in _leaves(reference):
        how = next((r for p, r in patterns if fnmatch.fnmatchcase(path, p)), Rule())
        owner = _owner(results, path)
        present, actual = _at(data, path)
        if owner is None or owner.status != "extracted" or not present or actual is None:
            if owner is None:
                why = "the path is not in the spec"
            elif owner.status == "extracted" and present:
                why = f"printed as {owner.printed!r}, which marks the value as not reported"
            elif owner.status == "extracted":
                why = "the extracted value has no such path"
            else:
                why = f"the field is {owner.status}"
            checks.append(Check(path, "not_extracted", expected, None, why))
            continue
        anchor = owner.anchor
        a, e = _numeric(actual), _number(expected)
        if a is not None and e is not None:
            limit = how.tolerance * abs(e) if how.relative else how.tolerance
            diff = abs(a - e)
            checks.append(
                Check(
                    path,
                    "match" if diff <= limit else "mismatch",
                    expected,
                    actual,
                    f"difference {diff}, tolerance {limit}",
                    anchor,
                )
            )
            continue
        if isinstance(actual, str) and isinstance(expected, str):
            ok = _text(actual, how.text) == _text(expected, how.text)
        else:
            ok = actual == expected
        checks.append(
            Check(
                path,
                "match" if ok else "mismatch",
                expected,
                actual,
                "" if ok else "values differ",
                anchor,
            )
        )
    return tuple(checks)
