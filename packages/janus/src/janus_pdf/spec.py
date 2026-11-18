"""Specs: which values to take from a document, where they are printed, and how to read them.

A spec is a YAML or JSON mapping. Each field names one locator and, optionally, a type:

    name: Supplier invoice
    fields:
      number: {label: "Invoice No."}
      date: {label: Date, type: date}
      due: {label: Due, type: date DD/MM/YYYY}
      total: {label: [Total due, Amount due], type: money GBP}
      items:
        records:
          header: {description: Description, qty: Qty, amount: Amount}
          stop: [Subtotal]
        columns: {qty: integer, amount: money GBP}
      survey:
        fields:
          length: {label: "Length, mm", column: Site A, type: mean_sd}

`load` checks everything up front and rejects unknown keys, so a misspelt option fails before
any document is read.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from janus_pdf.canonical import canonical_json
from janus_pdf.values import COMPONENTS, KINDS, ValueType


class SpecError(ValueError):
    """The spec is not valid. The message names the field."""


@dataclass(frozen=True, slots=True)
class Label:
    """The value printed beside a label: after it on the line, to its right, or in a table
    row's cell under `column`."""

    names: tuple[str, ...]
    column: str | None = None


@dataclass(frozen=True, slots=True)
class Cell:
    """A table cell by position or by row label and column header."""

    table: str | int  # "p5t0", or the n-th table in the document (1-based)
    row: int | str  # 0-based row, or the text of the row's first cell
    column: int | str  # 0-based column, or a column header


@dataclass(frozen=True, slots=True)
class Records:
    """Rows under a header, one record per row, until a stop label or the end of the rows."""

    header: tuple[tuple[str, str], ...]  # (key, printed column header)
    stop: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Section:
    """The text under a heading, up to the next heading printed at least as large."""

    heading: tuple[str, ...]
    under: str | None = None  # the nearest larger heading above it


@dataclass(frozen=True, slots=True)
class Region:
    """The words inside a box on a page, in PDF points from the top-left corner."""

    page: int
    box: tuple[float, float, float, float]


Locator = Label | Cell | Records | Section | Region
LOCATORS = ("label", "cell", "records", "section", "region")


@dataclass(frozen=True, slots=True)
class Field:
    """One value to extract: its path in the data, where it is printed, and how to read it."""

    path: str  # "total", "survey/length"
    locator: Locator
    type: ValueType = field(default_factory=ValueType)
    columns: tuple[tuple[str, ValueType], ...] = ()  # records only
    pages: tuple[int, int] | None = None  # first and last page to look on


@dataclass(frozen=True, slots=True)
class Spec:
    """A loaded spec: its fields in the order written, and a hash of the spec as written."""

    name: str
    fields: tuple[Field, ...]
    hash: str  # SHA-256 of the canonical JSON of the spec as written

    def field(self, path: str) -> Field:
        """The field at `path`."""
        return next(f for f in self.fields if f.path == path)


def load(source: str | Path | dict[str, Any]) -> Spec:
    """A spec from a YAML or JSON file, a YAML string, or a mapping."""
    if isinstance(source, dict):
        raw = source
    else:
        text = source.read_text() if isinstance(source, Path) else source
        if isinstance(source, str) and "\n" not in source and Path(source).is_file():
            text = Path(source).read_text()
        raw = yaml.safe_load(text)
    if not isinstance(raw, dict) or not isinstance(raw.get("fields"), dict):
        raise SpecError("a spec is a mapping with a `fields` mapping")
    _keys(raw, {"name", "fields"}, "the spec")
    fields = tuple(_fields(raw["fields"], ""))
    if not fields:
        raise SpecError("the spec has no fields")
    digest = hashlib.sha256(canonical_json(json.loads(json.dumps(raw)))).hexdigest()
    return Spec(name=str(raw.get("name", "")), fields=fields, hash=digest)


def _keys(raw: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(map(str, raw)) - allowed)
    if unknown:
        raise SpecError(f"{where}: unknown key(s) {', '.join(map(str, unknown))}")


def _names(value: Any, where: str) -> tuple[str, ...]:
    names = (value,) if isinstance(value, str) else tuple(value or ())
    if not names or not all(isinstance(n, str) and n.strip() for n in names):
        raise SpecError(f"{where}: expected a label or a list of labels")
    return names


def _fields(raw: dict[str, Any], prefix: str):
    for key, body in raw.items():
        path = f"{prefix}{key}"
        if not re.fullmatch(r"[A-Za-z_][\w-]*", str(key)):
            raise SpecError(f"{path}: field names are letters, digits, _ and -")
        if isinstance(body, dict) and "fields" in body:
            _keys(body, {"fields"}, path)
            yield from _fields(body["fields"], f"{path}/")
            continue
        if not isinstance(body, dict):
            raise SpecError(f"{path}: expected a mapping with one of {', '.join(LOCATORS)}")
        yield _field(path, body)


def _field(path: str, body: dict[str, Any]) -> Field:
    _keys(body, {*LOCATORS, "column", "under", "type", "columns", "pages"}, path)
    given = [k for k in LOCATORS if k in body]
    if len(given) != 1:
        raise SpecError(f"{path}: give exactly one of {', '.join(LOCATORS)}")
    kind = given[0]
    value = body[kind]
    if "column" in body and kind != "label":
        raise SpecError(f"{path}: `column` goes with `label`")
    if "under" in body and kind != "section":
        raise SpecError(f"{path}: `under` goes with `section`")
    if "columns" in body and kind != "records":
        raise SpecError(f"{path}: `columns` goes with `records`")
    try:
        match kind:
            case "label":
                locator: Locator = Label(_names(value, path), body.get("column"))
            case "cell":
                _keys(value, {"table", "row", "column"}, path)
                locator = Cell(value["table"], value["row"], value["column"])
            case "records":
                _keys(value, {"header", "stop"}, path)
                header = value["header"]
                if not isinstance(header, dict) or not header:
                    raise SpecError(f"{path}: records.header maps keys to printed headers")
                locator = Records(
                    tuple((str(k), str(v)) for k, v in header.items()),
                    _names(value["stop"], path) if value.get("stop") else (),
                )
            case "section":
                locator = Section(_names(value, path), body.get("under"))
            case "region":
                _keys(value, {"page", "box"}, path)
                box = tuple(float(v) for v in value["box"])
                if len(box) != 4:
                    raise SpecError(f"{path}: region.box is [x0, y0, x1, y1]")
                locator = Region(int(value["page"]), box)  # type: ignore[arg-type]
    except KeyError as exc:
        raise SpecError(f"{path}: {kind} needs {exc.args[0]}") from None
    vt = value_type(body.get("type", "text"), path)
    columns: tuple[tuple[str, ValueType], ...] = ()
    if isinstance(locator, Records):
        keys = {k for k, _ in locator.header}
        typed = body.get("columns") or {}
        if set(typed) - keys:
            raise SpecError(f"{path}: columns {sorted(set(typed) - keys)} are not in the header")
        columns = tuple(
            (k, value_type(typed.get(k, "text"), f"{path}/{k}")) for k, _ in locator.header
        )
    if isinstance(locator, Section) and vt.kind != "text":
        raise SpecError(f"{path}: a section is text")
    return Field(path, locator, vt, columns, _pages(body.get("pages"), path))


def _pages(value: Any, path: str) -> tuple[int, int] | None:
    if value is None:
        return None
    if isinstance(value, int):
        return (value, value)
    m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", str(value))
    if not m:
        raise SpecError(f"{path}: pages is a page number or a range such as 3-5")
    first = int(m.group(1))
    return (first, int(m.group(2) or first))


def value_type(raw: Any, path: str = "") -> ValueType:
    """A type from "integer", "date DD/MM/YYYY", "money EUR 1.234,56", "count_percent count",
    or a mapping such as {kind: date, formats: [D MMMM YYYY], locale: de}."""
    try:
        if isinstance(raw, dict):
            _keys(raw, {"kind", "numbers", "formats", "locale", "currency", "pick", "absent"}, path)
            options = dict(raw)
            if isinstance(options.get("formats"), str):
                options["formats"] = [options["formats"]]
            for key in ("formats", "absent"):
                if key in options:
                    options[key] = tuple(options[key])
            return ValueType(**options)
        if not isinstance(raw, str) or not raw.split():
            raise SpecError(f"{path}: a type is a name such as integer, or a mapping")
        kind, *rest = raw.split(maxsplit=1)
        if kind not in KINDS:
            raise SpecError(f"{path}: unknown type {kind!r}; known types: {', '.join(KINDS)}")
        if not rest:
            return ValueType(kind)  # type: ignore[arg-type]
        arg = rest[0].strip()
        if kind == "date":
            return ValueType("date", formats=(arg,))
        options: dict[str, Any] = {}
        sample = re.search(r"(?<!\S)1\D?234\D56(?!\S)", arg)
        if sample:
            options["numbers"] = sample.group()
            arg = arg[: sample.start()] + arg[sample.end() :]
        for token in arg.split():
            if kind == "money" and re.fullmatch(r"[A-Z]{3}", token):
                options["currency"] = token
            elif token in COMPONENTS.get(kind, ()):
                options["pick"] = token
            else:
                raise SpecError(f"{path}: cannot read {token!r} in type {raw!r}")
        return ValueType(kind, **options)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        if isinstance(exc, SpecError):
            raise
        raise SpecError(f"{path}: {exc}") from None
