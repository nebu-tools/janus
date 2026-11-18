"""Extraction: finding each field's printed value in a layer, reading it, and keeping the evidence.

A field counts as extracted only when all of these hold:

1. its locator finds the value in one place, or in several places that print the same value;
2. the printed text reads as the field's type, whole;
3. the value has anchors: its offsets in the layer text and its boxes on the page.

"The same value" is typed: numbers are the same when they are equal as numbers ("4.60" and
"4.6"), dates and codes when they are equal, and text when it is equal after spacing. A text
field printed "001" in one place and "1" in another is ambiguous.

Anything short of that gets another status and the reason: `missing` (nothing found; close
labels are offered as suggestions, never as values), `ambiguous` (several places disagree, or a
printed line could belong to two records; each is listed), `incomplete` (records that may go on
where the page cannot show they do), `invalid` (found, but the text does not read as the type),
or `unconfirmed` (a proposer offered a value the document does not bear out).
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from janus_pdf._index import View, index_of
from janus_pdf._locate import Found, Place, Rows, locate, locate_records
from janus_pdf.document import Anchor, Layer, make_anchor, quote_spans
from janus_pdf.spec import Field, Records, Spec
from janus_pdf.values import ParseError, ValueType, clean, parse

Status = Literal["extracted", "missing", "ambiguous", "incomplete", "invalid", "unconfirmed"]


@dataclass(frozen=True, slots=True)
class Candidate:
    """One place a locator found something, and what it reads as there."""

    page: int
    printed: str
    value: Any = None
    error: str | None = None
    anchors: tuple[Anchor, ...] = ()


@dataclass(frozen=True, slots=True)
class FieldResult:
    """One field's outcome: its status, its value when extracted, and the evidence for it.

    `anchors` has one anchor for each run of the value's words that follow one another in the
    layer text: one for a value on a line, several for a value in a region beside other text or
    a cell wrapped under a neighbour. `type` is the type the value was read as (None for a
    records field, whose cells carry their own).

    `method` names what found the value: "label", "cell", "records", "records:layout",
    "section", "region" or "proposed:<proposer name>". `candidates` lists every place found when
    there were several; `suggestions` lists near-miss labels for a person to accept or reject.
    """

    path: str
    status: Status
    value: Any = None
    printed: str | None = None
    anchors: tuple[Anchor, ...] = ()
    method: str = ""
    message: str = ""
    candidates: tuple[Candidate, ...] = ()
    suggestions: tuple[str, ...] = ()
    type: ValueType | None = None

    @property
    def page(self) -> int | None:
        """The page the value is printed on first, when it has anchors."""
        boxes = [b for a in self.anchors for b in a.boxes]
        return boxes[0].page if boxes else None


@dataclass(frozen=True, slots=True)
class Extraction:
    """Every field of a spec, read from one layer, with the hashes that identify all three."""

    spec: str
    document: str
    layer: str
    fields: tuple[FieldResult, ...]

    @property
    def data(self) -> dict[str, Any]:
        """Extracted values by path, nested by group. Anything not extracted is None."""
        out: dict[str, Any] = {}
        for r in self.fields:
            parts = r.path.split("/")
            if any(p.isdigit() for p in parts):
                continue  # record cells are inside their records value
            node = out
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = r.value if r.status == "extracted" else None
        return out

    def result(self, path: str) -> FieldResult:
        """The result for the field at `path`, such as "total" or "items/2/qty"."""
        return next(r for r in self.fields if r.path == path)


# --- The proposer seam --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Proposal:
    """A value some other reader (a language model, a vision model, Docling) thinks is printed.

    `quote` is the printed text of the value, copied exactly. `context` is a longer passage
    around it and `page` its page, used only when the quote alone is printed more than once.
    """

    value: Any
    quote: str
    context: str = ""
    page: int | None = None
    note: str = ""


class Proposer(Protocol):
    """Anything that can offer a value for a field the locators could not extract."""

    name: str

    def propose(self, layer: Layer, field: Field, result: FieldResult) -> Proposal | None:
        """A proposal for `field`, given the failed `result`, or None."""
        ...


# --- The extracted rule -------------------------------------------------------------------------


def _printed(view: View, place: Place) -> str:
    return clean(" ".join(view.text(s.start, s.end) for s in place))


def _read(view: View, path: str, vt: ValueType, found: Found) -> FieldResult:
    """Apply the extracted rule to what a locator found."""
    method = found.method
    if not found.places:
        return FieldResult(path, "missing", method=method, message=found.reason,
                           suggestions=found.suggestions, type=vt)  # fmt: skip
    cands, notes = [], []
    for place in dict.fromkeys(found.places):
        printed = _printed(view, place)
        anchors = tuple(make_anchor(view.layer, s) for s in place)
        page = view.page_of(place[0].start)
        try:
            parsed = parse(printed, vt)
        except ParseError as exc:
            cands.append(Candidate(page, printed, None, str(exc), anchors))
            continue
        cands.append(Candidate(page, printed, parsed.value, None, anchors))
        notes += [n for n in parsed.notes if n not in notes]
    good = [c for c in cands if c.error is None]
    if len(cands) == 1:
        (only,) = cands
        if only.error:
            return FieldResult(path, "invalid", None, only.printed, only.anchors, method,
                               only.error, type=vt)  # fmt: skip
        if not all(a.boxes for a in only.anchors):
            return FieldResult(path, "invalid", None, only.printed, only.anchors, method,
                               "the text has no boxes on the page", type=vt)  # fmt: skip
        return FieldResult(path, "extracted", only.value, only.printed, only.anchors, method,
                           "; ".join(notes), type=vt)  # fmt: skip
    if len(good) == len(cands) and all(vt.same(c.value, good[0].value) for c in good):
        pages = sorted({c.page for c in good})
        message = "; ".join([f"printed {len(good)} times (pages {pages}), all the same", *notes])
        first = good[0]
        return FieldResult(path, "extracted", first.value, first.printed, first.anchors, method,
                           message, tuple(cands), type=vt)  # fmt: skip
    places = ", ".join(f"p{c.page} {c.printed[:40]!r}" for c in cands)
    message = f"{len(cands)} places disagree: {places}" + (f"; {found.hint}" if found.hint else "")
    return FieldResult(path, "ambiguous", None, None, (), method, message, tuple(cands), type=vt)


def _pages(pages: tuple[int, ...]) -> str:
    return f"page {pages[0]}" if len(pages) == 1 else f"pages {', '.join(map(str, pages))}"


def _records(view: View, f: Field, loc: Records) -> list[FieldResult]:
    rows = locate_records(view, loc)
    if rows is None:
        headers = ", ".join(h for _, h in loc.header)
        message = f"no table row or printed row holds all of: {headers}"
        return [FieldResult(f.path, "missing", method="records", message=message)]
    printed = clean(view.text(rows.header.start, rows.header.end))
    anchors = (make_anchor(view.layer, rows.header),)
    found = _found(rows)
    if rows.incomplete or rows.ambiguous:
        status: Status = "incomplete" if rows.incomplete else "ambiguous"
        message = f"{found}; {rows.incomplete or rows.ambiguous}"
        return [FieldResult(f.path, status, None, printed, anchors, rows.method, message)]
    if not rows.rows:
        message = "the header is printed, but no rows follow it"
        return [FieldResult(f.path, "missing", None, printed, anchors, rows.method, message)]
    types = dict(f.columns)
    results: list[FieldResult] = []
    records: list[dict[str, Any]] = []
    for row in rows.rows:
        n = len(records)
        record: dict[str, Any] = {}
        for key, _ in loc.header:
            place = row.cells.get(key)
            cell = Found(rows.method, [place] if place else [], "nothing printed in this column")
            r = _read(view, f"{f.path}/{n}/{key}", types[key], cell)
            results.append(r)
            record[key] = r.value if r.status == "extracted" else None
        records.append(record)
    bad = sum(r.status != "extracted" for r in results)
    message = found + (f"; {bad} cell(s) not extracted" if bad else "")
    head = FieldResult(f.path, "extracted", records, printed, anchors, rows.method, message)
    return [head, *results]


def _found(rows: Rows) -> str:
    """What a records locator found, for the message."""
    pages = sorted({r.page for r in rows.rows}) or list(rows.pages[:1])
    n = len(rows.rows)
    out = f"{n} {'row' if n == 1 else 'rows'} under the header on {_pages(tuple(pages))}"
    if rows.skipped:
        out += f", leaving out {', '.join(rows.skipped)}"
    return out


def _confirm(
    view: View, f: Field, proposal: Proposal, name: str, before: FieldResult
) -> FieldResult:
    """Check a proposal against the page. A confirmed proposal becomes an extracted value: its
    quote must be printed once on the field's pages and read, under the field's type, as the
    proposed value."""
    method = f"proposed:{name}"

    def unconfirmed(why: str) -> FieldResult:
        message = f"{why} (before the proposal: {before.status}: {before.message})"
        return FieldResult(f.path, "unconfirmed", None, proposal.quote, (), method, message,
                           before.candidates, before.suggestions, f.type)  # fmt: skip

    def on_page(spans):
        return [
            s
            for s in spans
            if view.on(view.page_of(s.start))
            and (proposal.page is None or view.page_of(s.start) == proposal.page)
        ]

    text = view.layer.text
    spans = on_page(quote_spans(text, proposal.quote))
    if not spans:
        where = "" if f.pages is None else " on the field's pages"
        return unconfirmed(f"the quote is not printed in the document{where}")
    if len(spans) > 1 and proposal.context:
        hosts = on_page(quote_spans(text, proposal.context))
        spans = [s for s in spans if any(h.start <= s.start and s.end <= h.end for h in hosts)]
    if len(spans) != 1:
        return unconfirmed(f"the quote is printed {len(spans)} times; a context would pick one")
    (span,) = spans
    try:
        parsed = parse(text[span.start : span.end], f.type)
    except ParseError as exc:
        return unconfirmed(f"the quote is printed, but {exc}")
    if not f.type.same(parsed.value, proposal.value):
        return unconfirmed(f"the quote reads as {parsed.value!r}, not {proposal.value!r}")
    anchor = make_anchor(view.layer, span)
    message = f"confirmed by its quote on page {view.page_of(span.start)}"
    message = "; ".join([message, *parsed.notes, *([proposal.note] if proposal.note else [])])
    return FieldResult(f.path, "extracted", parsed.value, clean(anchor.quote.exact), (anchor,),
                       method, message, type=f.type)  # fmt: skip


def extract(layer: Layer, spec: Spec, proposer: Proposer | None = None) -> Extraction:
    """Every field of `spec` from `layer`.

    Each field reads the layer through a view of its `pages`, so every locator, and the check of
    a proposal, sees only those pages. A proposer, when given, is asked only about fields the
    locators could not extract, and its answers are checked against the page. The layer's index
    is built on the first call and reused while the same layer is extracted from or inspected.
    """
    ix = index_of(layer)
    results: list[FieldResult] = []
    for f in spec.fields:
        view = ix.view(f.pages)
        if isinstance(f.locator, Records):
            results += _records(view, f, f.locator)
            continue
        r = _read(view, f.path, f.type, locate(view, f))
        if r.status != "extracted" and proposer is not None:
            proposal = proposer.propose(layer, f, r)
            if proposal is not None:
                r = _confirm(view, f, proposal, proposer.name, r)
        results.append(r)
    return Extraction(spec.hash, layer.document_hash, layer.id, tuple(results))
