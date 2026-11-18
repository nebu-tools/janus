"""Comparing an extraction with reference data someone else produced.

The reference is plain data shaped like the extraction's `data`: the values a person typed in,
an accounting system's export, last year's report. Every leaf of the reference is checked
against the extracted value at the same path, so the reference decides what is compared.

    checks = compare(extraction, {"total": {"amount": "627.00", "currency": "GBP"}},
                     rules={"*/amount": {"tolerance": "0.01"}})

Each leaf compares as the field's type says. A number (an integer, a decimal, a percent, the
amount of money) compares as a decimal, within an absolute or relative tolerance, and the
reference may give it as a number or as a plain decimal string. Text compares exactly, or
ignoring case and spacing, and only with text: an invoice number printed "001" does not match
a reference 1. Dates, currencies and comparators compare exactly. A value that was not
extracted is never a match or a mismatch: it is reported as `not_extracted`, so a missing value
cannot pass as agreement.
"""

import fnmatch
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from janus_pdf.document import Anchor
from janus_pdf.extract import Extraction, FieldResult
from janus_pdf.values import Scalar, as_number

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


def _owners(results: dict[str, FieldResult], path: str) -> list[FieldResult]:
    """The field results a leaf belongs to, longest path first: a record's cell, then the
    records field it is part of."""
    parts = path.split("/")
    found = (results.get("/".join(parts[:n])) for n in range(len(parts), 0, -1))
    return [r for r in found if r is not None]


def _scalar(owner: FieldResult, path: str) -> Scalar | None:
    """How the leaf at `path` of `owner`'s value compares, from the owner's type."""
    if owner.type is None:
        return None
    rest = path[len(owner.path) + 1 :] if path != owner.path else None
    try:
        return owner.type.scalar(rest)
    except ValueError:
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
        owners = _owners(results, path)
        present, actual = _at(data, path)
        failed = next((o for o in reversed(owners) if o.status != "extracted"), None)
        if not owners or failed is not None or not present or actual is None:
            if not owners:
                why = "the path is not in the spec"
            elif failed is not None:
                why = f"{failed.path} is {failed.status}"
            elif present:
                why = f"printed as {owners[0].printed!r}, which marks the value as not reported"
            else:
                why = "the extracted value has no such path"
            checks.append(Check(path, "not_extracted", expected, None, why))
            continue
        owner = owners[0]
        anchor = owner.anchors[0] if owner.anchors else None
        how_compared = _scalar(owner, path)
        if how_compared == "number":
            a, e = as_number(actual), as_number(expected)
            if a is None or e is None:
                checks.append(Check(path, "mismatch", expected, actual,
                                    "the reference is not a number", anchor))  # fmt: skip
                continue
            limit = how.tolerance * abs(e) if how.relative else how.tolerance
            diff = abs(a - e)
            status: CheckStatus = "match" if diff <= limit else "mismatch"
            checks.append(Check(path, status, expected, actual,
                                f"difference {diff}, tolerance {limit}", anchor))  # fmt: skip
            continue
        if how_compared == "text":
            ok = isinstance(expected, str) and _text(actual, how.text) == _text(expected, how.text)
            why = "" if ok else ("the reference is not text" if not isinstance(expected, str)
                                 else "values differ")  # fmt: skip
        else:
            ok = actual == expected
            why = "" if ok else "values differ"
        checks.append(Check(path, "match" if ok else "mismatch", expected, actual, why, anchor))
    return tuple(checks)
