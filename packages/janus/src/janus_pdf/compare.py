"""Comparing an extraction with reference data someone else produced.

The reference is plain data shaped like the extraction's `data`: the values a person typed in,
an accounting system's export, last year's report. Every leaf of the reference is checked
against the extracted value at the same path, so the reference decides what is compared.

    checks = compare(extraction, {"total": {"amount": "627.00", "currency": "GBP"}},
                     rules={"*/amount": {"tolerance": "0.01"}})

Each leaf is equal when the field's type says the two values are the same value
(`ValueType.same`), the rule extraction uses to tell whether two printed places agree: numbers
(an integer, a decimal, a percent, the amount of money) as decimals, text after spacing, dates,
currencies and comparators exactly. A reference number may be a number or a plain decimal
string; text matches only text, so an invoice number printed "001" does not match a reference 1.
Values are compared by their type's equality; `casefold: true` loosens text, `tolerance:`
loosens numbers, nothing else does. A value that was not
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


@dataclass(frozen=True, slots=True)
class Rule:
    """How to compare the leaves a path pattern matches."""

    tolerance: Decimal = Decimal(0)
    relative: bool = False  # tolerance is a fraction of the reference value
    casefold: bool = False  # text that differs only in case matches


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
    """A rule from a mapping such as {tolerance: 0.01, relative: false, casefold: true}."""
    if isinstance(raw, Rule):
        return raw
    if not isinstance(raw, Mapping):
        raise ValueError(f"a rule is a mapping of options, not {raw!r}")
    unknown = set(raw) - {"tolerance", "relative", "casefold"}
    if unknown:
        raise ValueError(f"unknown rule option(s): {', '.join(sorted(map(str, unknown)))}")
    tolerance = raw.get("tolerance", 0)
    try:
        if isinstance(tolerance, bool):
            raise ArithmeticError
        amount = Decimal(str(tolerance))
        if not amount.is_finite() or amount < 0:
            raise ArithmeticError
    except ArithmeticError:
        raise ValueError(f"tolerance: expected a number of 0 or more, not {tolerance!r}") from None
    flags = []
    for name in ("relative", "casefold"):
        value = raw.get(name, False)
        if not isinstance(value, bool):
            raise ValueError(f"{name}: expected true or false, not {value!r}")
        flags.append(value)
    return Rule(amount, *flags)


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


def _scalar(owner: FieldResult, path: str) -> tuple[Scalar, str | None] | None:
    """How the leaf at `path` of `owner`'s value compares, from the owner's type, and the
    component the leaf is."""
    if owner.type is None:
        return None
    rest = path[len(owner.path) + 1 :] if path != owner.path else None
    try:
        return owner.type.scalar(rest), rest
    except ValueError:
        return None


def compare(
    extraction: Extraction,
    reference: dict[str, Any],
    rules: Mapping[str, Mapping[str, Any] | Rule] | None = None,
) -> tuple[Check, ...]:
    """One check per leaf of `reference`. `rules` maps path patterns ("total/amount",
    "lines/*/amount/amount", "*") to options; the first pattern that matches applies."""
    if not isinstance(reference, dict):
        raise ValueError(
            f"the reference is a mapping shaped like the extraction's data, not {reference!r}"
        )
    if rules is not None and not isinstance(rules, Mapping):
        raise ValueError(f"rules map path patterns to options, not {rules!r}")
    patterns = [(str(p), rule(r)) for p, r in (rules or {}).items()]
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
        scalar = _scalar(owner, path)
        if scalar is None or owner.type is None:
            ok = actual == expected
            checks.append(Check(path, "match" if ok else "mismatch", expected, actual,
                                "" if ok else "values differ", anchor))  # fmt: skip
            continue
        how_compared, component = scalar
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
        if how_compared == "text" and not isinstance(expected, str):
            ok, why = False, "the reference is not text"
        else:
            a, e = actual, expected
            if how_compared == "text" and how.casefold:
                a, e = a.casefold(), e.casefold()
            ok = owner.type.same(a, e, component)
            why = "" if ok else "values differ"
        checks.append(Check(path, "match" if ok else "mismatch", expected, actual, why, anchor))
    return tuple(checks)
