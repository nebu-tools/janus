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
          skip: [Carried forward]  # rows to leave out
          continues: header        # the table runs over pages that print its header again
          filled: {first: [qty]}   # a line without a qty continues the record above
        columns: {qty: integer, amount: money GBP}
      survey:
        fields:
          length: {label: "Length, mm", column: Site A, type: mean_sd}

`load` checks everything up front against one schema, so a misspelt option, a value of the
wrong kind or a spec that contradicts itself fails as a `SpecError` naming the field and the
key, before any document is read.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal, cast

import yaml
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)
from pydantic import Field as Constraint
from pydantic_core import PydanticCustomError

from janus_pdf._index import normalize_label
from janus_pdf.canonical import canonical_json
from janus_pdf.values import KINDS, PARTS, Kind, ValueType


class SpecError(ValueError):
    """The spec is not valid. The message names the field and the key."""


@dataclass(frozen=True, slots=True)
class Label:
    """The value printed beside a label: after it on the line, to its right, or in a table
    row's cell under `column`."""

    names: tuple[str, ...]
    column: str | None = None


@dataclass(frozen=True, slots=True)
class Cell:
    """A table cell by position or by row label and column header."""

    table: str | int  # "p5t0", or the n-th table on the field's pages (1-based)
    row: int | str  # 0-based row, or the text of the row's first cell
    column: int | str  # 0-based column, or a column header


@dataclass(frozen=True, slots=True)
class Records:
    """Rows under a header, one record per row, until a stop label or the end of the rows.

    What the page cannot show, the spec declares. `stop` names the rows that end the table and
    `skip` the rows to leave out of it, each by the text the row begins with. `continues` says
    that the table runs over pages: "header" over each following page that opens with the same
    header, "rows" over each following page that opens with rows on the same column edges; with
    None a records field reads one table on one page. `filled`, for tables without rules only,
    names the columns every record fills on its first line (`filled_on` "first") or on its last
    line ("last"), so that a printed line filling only some columns can be given to a record;
    without it such a line makes the field ambiguous.
    """

    header: tuple[tuple[str, str], ...]  # (key, printed column header)
    stop: tuple[str, ...] = ()
    skip: tuple[str, ...] = ()
    continues: Literal["header", "rows"] | None = None
    filled: tuple[str, ...] = ()
    filled_on: Literal["first", "last"] = "first"


@dataclass(frozen=True, slots=True)
class Section:
    """The text under a heading, up to the next heading printed at least as large."""

    heading: tuple[str, ...]
    under: str | None = None  # the nearest larger heading above it


@dataclass(frozen=True, slots=True)
class Region:
    """The words inside a box on a page, in PDF points from the top-left corner of the page as
    displayed. A word is inside when the centre of its box is."""

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


# --- The schema ---------------------------------------------------------------------------------
#
# The models below describe a spec as written. They check the shape and the kind of every value;
# `_field` then turns one into a `Field` and checks what the shape cannot say.


def _listed(value: Any) -> Any:
    return (value,) if isinstance(value, str) else value


Text = Annotated[StrictStr, StringConstraints(pattern=r"\S")]
Names = Annotated[tuple[Text, ...], BeforeValidator(_listed), Constraint(min_length=1)]
Index = Annotated[StrictInt, Constraint(ge=0)]
Positive = Annotated[StrictInt, Constraint(ge=1)]
Number = StrictInt | StrictFloat
PageRange = Annotated[StrictStr, StringConstraints(pattern=r"^\s*\d+\s*(-\s*\d+\s*)?$")]
TableId = Annotated[StrictStr, StringConstraints(pattern=r"^p[1-9]\d*t\d+$")]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="before")
    @classmethod
    def _given(cls, data: Any) -> Any:
        """A key written with no value is an error, not the key left out."""
        if isinstance(data, dict):
            for key, value in data.items():
                if value is None:
                    raise PydanticCustomError("no_value", "no value given", {"key": key})
        return data


class _CellSpec(_Model):
    table: TableId | Positive
    row: Index | Text
    column: Index | Text


class _FilledSpec(_Model):
    first: Names | None = None
    last: Names | None = None


class _RecordsSpec(_Model):
    header: Annotated[dict[StrictStr, Text], Constraint(min_length=1)]
    stop: Names = ()
    skip: Names = ()
    continues: Literal["header", "rows"] | None = None
    filled: _FilledSpec | None = None


class _RegionSpec(_Model):
    page: Positive
    box: tuple[Number, Number, Number, Number]


class _TypeSpec(_Model):
    kind: StrictStr
    numbers: StrictStr = "1,234.56"
    formats: Names = ()
    locale: StrictStr = "en"
    currency: StrictStr | None = None
    pick: StrictStr | None = None
    absent: tuple[StrictStr, ...] = ()
    bounds: Literal["share", "any"] = "share"


TypeSpec = Text | _TypeSpec


class _FieldSpec(_Model):
    label: Names | None = None
    cell: _CellSpec | None = None
    records: _RecordsSpec | None = None
    section: Names | None = None
    region: _RegionSpec | None = None
    column: Text | None = None
    under: Text | None = None
    type: TypeSpec = "text"
    columns: dict[StrictStr, TypeSpec] = {}
    pages: Positive | PageRange | None = None


class _GroupSpec(_Model):
    fields: dict[StrictStr | StrictInt, Any]


class _SpecSpec(_Model):
    name: StrictStr = ""
    fields: dict[StrictStr | StrictInt, Any]


# What each key holds, for messages.
_EXPECTED = {
    "label": "a label or a list of labels",
    "section": "a heading or a list of headings",
    "cell": "a mapping with table, row and column",
    "cell.table": "a table id such as p1t0, or a table number from 1",
    "cell.row": "a row number from 0, or the text of the row's first cell",
    "cell.column": "a column number from 0, or a column header",
    "records": "a mapping with header and, optionally, stop, skip, continues and filled",
    "records.header": "a mapping from keys to printed column headers",
    "records.stop": "a label or a list of labels",
    "records.skip": "a label or a list of labels",
    "records.continues": "header or rows",
    "records.filled": "a mapping with first or last",
    "records.filled.first": "a header key or a list of them",
    "records.filled.last": "a header key or a list of them",
    "region": "a mapping with page and box",
    "region.page": "a page number from 1",
    "region.box": "four numbers [x0, y0, x1, y1]",
    "column": "a column header",
    "under": "a heading",
    "type": "a type name such as integer, or a mapping with kind",
    "columns": "a mapping from header keys to types",
    "pages": "a page number or a range such as 3-5",
    "fields": "a mapping of fields",
    "name": "text",
    "kind": "a type name",
    "numbers": "a sample number such as 1,234.56",
    "formats": "a date format or a list of them",
    "locale": "a locale such as en or de",
    "currency": "an ISO 4217 code such as EUR",
    "pick": "the name of a component",
    "absent": "a list of not-reported marks",
    "bounds": "share or any",
}


def _key(loc: tuple[str | int, ...], model: type[BaseModel]) -> str:
    """The spec key an error is about, such as "cell.row" or "columns.qty": the model field
    names in `loc`, and the keys of the mappings that hold types and headers, without pydantic's
    names for union arms."""
    names: list[str] = []
    current: type[BaseModel] | None = model
    for part in loc:
        fields = current.model_fields if current is not None else None
        if fields is not None and isinstance(part, str) and part in fields:
            names.append(part)
            current = _model_of(fields[part].annotation)
        elif fields is None and names and names[-1] in ("columns", "header"):
            names.append(str(part))
    return ".".join(names)


def _model_of(annotation: Any) -> type[BaseModel] | None:
    for arm in getattr(annotation, "__args__", (annotation,)):
        if isinstance(arm, type) and issubclass(arm, BaseModel):
            return arm
    return None


def _validate[M: BaseModel](model: type[M], raw: Any, where: str) -> M:
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        # The deepest error is the most specific: inside a mapping rather than about its kind.
        error = max(exc.errors(), key=lambda e: len(e["loc"]))
        raise SpecError(_message(error, model, where)) from None


def _message(error: Any, model: type[BaseModel], where: str) -> str:
    """One pydantic error as `where: key: what was expected, not what was given`."""
    loc, kind = error["loc"], error["type"]
    key = _key(loc, model)

    def at(name: str) -> str:
        return ".".join(p for p in (key, name) if p)

    if kind == "no_value":
        return f"{where}: {at(str(error['ctx']['key']))}: no value given"
    if kind == "extra_forbidden":
        return f"{where}: unknown key {at(str(loc[-1]))}"
    if kind == "missing" and loc and key.endswith(str(loc[-1])):
        outer, _, missing = key.rpartition(".")
        return f"{where}: {outer} needs {missing}" if outer else f"{where} needs {missing}"
    if not key:
        return f"{where}: expected a mapping, not {_shown(error['input'])}"
    if key.startswith("columns."):
        expected = _EXPECTED["type"]
    elif key.startswith("records.header."):
        expected = _EXPECTED["column"]
    else:
        expected = _EXPECTED.get(key) or _EXPECTED.get(key.rsplit(".", 1)[-1], "another kind")
    return f"{where}: {key}: expected {expected}, not {_shown(error['input'])}"


def _shown(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= 40 else text[:39] + "…"


# --- Loading ------------------------------------------------------------------------------------


def load(source: str | Path | dict[str, Any]) -> Spec:
    """A spec from a YAML or JSON file, a YAML string, or a mapping."""
    raw: Any = source
    if isinstance(source, (str, Path)):
        text = source.read_text() if isinstance(source, Path) else source
        if isinstance(source, str) and "\n" not in source and Path(source).is_file():
            text = Path(source).read_text()
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise SpecError(f"the spec is not YAML or JSON: {exc}") from None
    spec = _validate(_SpecSpec, raw, "the spec")
    fields = tuple(_fields(spec.fields, ""))
    if not fields:
        raise SpecError("the spec has no fields")
    digest = hashlib.sha256(canonical_json(json.loads(json.dumps(raw)))).hexdigest()
    return Spec(name=spec.name, fields=fields, hash=digest)


def _fields(raw: dict[str | int, Any], prefix: str):
    for key, body in raw.items():
        path = f"{prefix}{key}"
        if not re.fullmatch(r"[A-Za-z_][\w-]*", str(key)):
            raise SpecError(f"{path}: field names are letters, digits, _ and -")
        if isinstance(body, dict) and "fields" in body:
            yield from _fields(_validate(_GroupSpec, body, path).fields, f"{path}/")
            continue
        if not isinstance(body, dict):
            raise SpecError(
                f"{path}: expected a mapping with one of {', '.join(LOCATORS)}, not {_shown(body)}"
            )
        yield _field(path, _validate(_FieldSpec, body, path))


def _field(path: str, body: _FieldSpec) -> Field:
    given = [k for k in LOCATORS if getattr(body, k) is not None]
    if len(given) != 1:
        raise SpecError(f"{path}: give exactly one of {', '.join(LOCATORS)}")
    for key, owner in (("column", "label"), ("under", "section"), ("columns", "records")):
        if key in body.model_fields_set and given[0] != owner:
            raise SpecError(f"{path}: `{key}` goes with `{owner}`")
    pages = _pages(body.pages, path)
    locator: Locator
    if body.label is not None:
        locator = Label(body.label, body.column)
    elif body.cell is not None:
        c = body.cell
        locator = Cell(c.table, c.row, c.column)
        if (
            isinstance(c.table, str)
            and pages
            and not _within(int(c.table[1:].split("t")[0]), pages)
        ):
            raise SpecError(f"{path}: cell.table {c.table} is not on pages {_range(pages)}")
    elif body.records is not None:
        r = body.records
        filled: tuple[str, ...] = ()
        on: Literal["first", "last"] = "first"
        if r.filled is not None:
            given_on = [k for k in ("first", "last") if getattr(r.filled, k) is not None]
            if len(given_on) != 1:
                raise SpecError(f"{path}: records.filled takes one of first or last")
            on = cast("Literal['first', 'last']", given_on[0])
            filled = getattr(r.filled, on)
            if unknown := [k for k in filled if k not in r.header]:
                raise SpecError(f"{path}: records.filled.{on} {unknown[0]!r} is not a header key")
        both = {normalize_label(s) for s in r.stop} & {normalize_label(s) for s in r.skip}
        if both:
            raise SpecError(f"{path}: records.stop and records.skip both name {sorted(both)[0]!r}")
        locator = Records(tuple(r.header.items()), r.stop, r.skip, r.continues, filled, on)
    elif body.section is not None:
        locator = Section(body.section, body.under)
    else:
        assert body.region is not None
        g = body.region
        x0, y0, x1, y1 = (float(v) for v in g.box)
        if not (x0 < x1 and y0 < y1):
            raise SpecError(f"{path}: region.box is [x0, y0, x1, y1] with x0 < x1 and y0 < y1")
        if pages and not _within(g.page, pages):
            raise SpecError(f"{path}: region.page {g.page} is not on pages {_range(pages)}")
        locator = Region(g.page, (x0, y0, x1, y1))
    vt = _type(body.type, path, "type")
    columns: tuple[tuple[str, ValueType], ...] = ()
    if isinstance(locator, Records):
        keys = [k for k, _ in locator.header]
        if unknown := sorted(set(body.columns) - set(keys)):
            raise SpecError(f"{path}: columns {unknown} are not in the header")
        columns = tuple((k, _type(body.columns.get(k, "text"), path, f"columns.{k}")) for k in keys)
    if isinstance(locator, Section) and vt.kind != "text":
        raise SpecError(f"{path}: a section is text")
    return Field(path, locator, vt, columns, pages)


def _within(page: int, pages: tuple[int, int]) -> bool:
    return pages[0] <= page <= pages[1]


def _range(pages: tuple[int, int]) -> str:
    return str(pages[0]) if pages[0] == pages[1] else f"{pages[0]}-{pages[1]}"


def _pages(value: int | str | None, path: str) -> tuple[int, int] | None:
    if value is None:
        return None
    if isinstance(value, int):
        return (value, value)
    first, _, last = value.replace(" ", "").partition("-")
    pages = (int(first), int(last or first))
    if pages[0] < 1 or pages[1] < pages[0]:
        raise SpecError(f"{path}: pages: {value!r} is not a range of pages from 1")
    return pages


class _TypeOnly(_Model):
    type: TypeSpec


def _type(spec: TypeSpec, path: str, key: str) -> ValueType:
    try:
        return _value_type(spec)
    except ValueError as exc:
        raise SpecError(f"{path}: {key}: {exc}") from None


def _value_type(spec: str | _TypeSpec) -> ValueType:
    if isinstance(spec, _TypeSpec):
        options = spec.model_dump(exclude_unset=True)
        for name in ("formats", "absent"):
            if name in options:
                options[name] = tuple(options[name])
        return ValueType(**options)
    name, *rest = spec.split(maxsplit=1)
    if name not in KINDS:
        raise ValueError(f"unknown type {name!r}; known types: {', '.join(KINDS)}")
    kind = cast("Kind", name)
    if not rest:
        return ValueType(kind)
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
        elif token in PARTS.get(kind, ()):
            options["pick"] = token
        elif kind == "percent" and token == "any":
            options["bounds"] = "any"
        else:
            raise ValueError(f"cannot read {token!r} in type {spec!r}")
    return ValueType(kind, **options)


def value_type(raw: Any, path: str = "") -> ValueType:
    """A type from "integer", "date DD/MM/YYYY", "money EUR 1.234,56", "count_percent count",
    "percent any", or a mapping such as {kind: date, formats: [D MMMM YYYY], locale: de}."""
    where = path or "the type"
    return _type(_validate(_TypeOnly, {"type": raw}, where).type, where, "type")
