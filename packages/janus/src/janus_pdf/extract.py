"""Extraction: finding each field's printed value in a layer, reading it, and keeping the evidence.

A field counts as extracted only when all of these hold:

1. its locator finds the value in one place, or in several places that print the same value;
2. the printed text reads as the field's type, whole;
3. the value has an anchor: its offsets in the layer text and its boxes on the page.

Anything short of that gets another status and the reason: `missing` (nothing found; close
labels are offered as suggestions, never as values), `ambiguous` (several places disagree; each
is listed), `invalid` (found, but the text does not read as the type), or `unconfirmed` (a
proposer offered a value the document does not bear out).
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from janus_pdf._index import Index, index_of, normalize_label
from janus_pdf._locate import Found, locate, locate_records
from janus_pdf.document import Anchor, Layer, Span, make_anchor, quote_spans
from janus_pdf.spec import Field, Records, Spec
from janus_pdf.values import ParseError, ValueType, clean, parse, same_value

Status = Literal["extracted", "missing", "ambiguous", "invalid", "unconfirmed"]


@dataclass(frozen=True, slots=True)
class Candidate:
    """One place a locator found something, and what it reads as there."""

    page: int
    printed: str
    value: Any = None
    error: str | None = None
    anchor: Anchor | None = None


@dataclass(frozen=True, slots=True)
class FieldResult:
    """One field's outcome: its status, its value when extracted, and the evidence for it.

    `method` names what found the value: "label", "cell", "records", "records:layout",
    "section", "region" or "proposed:<proposer name>". `candidates` lists every place found when
    there were several; `suggestions` lists near-miss labels for a person to accept or reject.
    """

    path: str
    status: Status
    value: Any = None
    printed: str | None = None
    anchor: Anchor | None = None
    method: str = ""
    message: str = ""
    candidates: tuple[Candidate, ...] = ()
    suggestions: tuple[str, ...] = ()


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


def _read(ix: Index, path: str, vt: ValueType, found: Found) -> FieldResult:
    """Apply the extracted rule to what a locator found."""
    method = found.method
    if not found.spans:
        return FieldResult(
            path, "missing", method=method, message=found.reason, suggestions=found.suggestions
        )
    cands, notes = [], []
    for s in dict.fromkeys(found.spans):
        printed = ix.text(s.start, s.end)
        anchor = make_anchor(ix.layer, s)
        try:
            parsed = parse(printed, vt)
        except ParseError as exc:
            cands.append(Candidate(ix.page_of(s.start), clean(printed), None, str(exc), anchor))
            continue
        cands.append(Candidate(ix.page_of(s.start), clean(printed), parsed.value, None, anchor))
        notes += parsed.notes
    good = [c for c in cands if c.error is None]
    if len(cands) == 1:
        (only,) = cands
        if only.error:
            return FieldResult(path, "invalid", None, only.printed, only.anchor, method, only.error)
        if only.anchor is None or not only.anchor.boxes:
            message = "the text has no boxes on the page"
            return FieldResult(path, "invalid", None, only.printed, only.anchor, method, message)
        return FieldResult(path, "extracted", only.value, only.printed, only.anchor, method,
                           "; ".join(notes))  # fmt: skip
    if len(good) == len(cands) and all(same_value(c.value, good[0].value) for c in good):
        pages = sorted({c.page for c in good})
        message = "; ".join([f"printed {len(good)} times (pages {pages}), all the same", *notes])
        first = good[0]
        return FieldResult(path, "extracted", first.value, first.printed, first.anchor, method,
                           message, tuple(cands))  # fmt: skip
    places = ", ".join(f"p{c.page} {c.printed[:40]!r}" for c in cands)
    message = f"{len(cands)} places disagree: {places}" + (f"; {found.hint}" if found.hint else "")
    return FieldResult(path, "ambiguous", None, None, None, method, message, tuple(cands))


def _records(ix: Index, f: Field, loc: Records) -> list[FieldResult]:
    rows = locate_records(ix, loc)
    if rows is None:
        headers = ", ".join(h for _, h in loc.header)
        message = f"no table row or printed row holds all of: {headers}"
        return [FieldResult(f.path, "missing", method="records", message=message)]
    stops = [normalize_label(s) for s in loc.stop]
    types = dict(f.columns)
    results: list[FieldResult] = []
    records: list[dict[str, Any]] = []
    for row in rows.rows:
        if any(normalize_label(row.first).startswith(s) for s in stops):
            break
        if not row.cells:
            continue
        record: dict[str, Any] = {}
        for key, _ in loc.header:
            span = row.cells.get(key)
            found = Found(rows.method, [span] if span else [], "nothing printed in this column")
            r = _read(ix, f"{f.path}/{len(records)}/{key}", types[key], found)
            results.append(r)
            record[key] = r.value if r.status == "extracted" else None
        records.append(record)
    header = rows.header
    page = ix.page_of(header.start)
    if not records:
        message = "the header is printed, but no rows follow it"
        return [FieldResult(f.path, "missing", None, None, None, rows.method, message)]
    bad = sum(r.status != "extracted" for r in results)
    message = f"{len(records)} rows under the header on page {page}"
    if bad:
        message += f"; {bad} cell(s) not extracted"
    printed = clean(ix.text(header.start, header.end))
    anchor = make_anchor(ix.layer, header)
    head = FieldResult(f.path, "extracted", records, printed, anchor, rows.method, message)
    return [head, *results]


def _confirm(
    ix: Index, f: Field, proposal: Proposal, name: str, before: FieldResult
) -> FieldResult:
    """Check a proposal against the page. A confirmed proposal becomes an extracted value."""
    method = f"proposed:{name}"

    def unconfirmed(why: str) -> FieldResult:
        message = f"{why} (before the proposal: {before.status}: {before.message})"
        return FieldResult(f.path, "unconfirmed", None, proposal.quote, None, method, message,
                           before.candidates, before.suggestions)  # fmt: skip

    def on_page(spans: tuple[Span, ...]) -> list[Span]:
        return [s for s in spans if proposal.page is None or ix.page_of(s.start) == proposal.page]

    text = ix.layer.text
    spans = on_page(quote_spans(text, proposal.quote))
    if not spans:
        return unconfirmed("the quote is not printed in the document")
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
    if not same_value(parsed.value, proposal.value):
        return unconfirmed(f"the quote reads as {parsed.value!r}, not {proposal.value!r}")
    anchor = make_anchor(ix.layer, span)
    message = f"confirmed by its quote on page {ix.page_of(span.start)}"
    message = "; ".join([message, *parsed.notes, *([proposal.note] if proposal.note else [])])
    return FieldResult(f.path, "extracted", parsed.value, clean(anchor.quote.exact), anchor,
                       method, message)  # fmt: skip


def extract(layer: Layer, spec: Spec, proposer: Proposer | None = None) -> Extraction:
    """Every field of `spec` from `layer`.

    A proposer, when given, is asked only about fields the locators could not extract, and its
    answers are checked against the page. The layer's index is built on the first call and
    reused while the same layer is extracted from or inspected.
    """
    ix = index_of(layer)
    results: list[FieldResult] = []
    for f in spec.fields:
        if isinstance(f.locator, Records):
            results += _records(ix, f, f.locator)
            continue
        r = _read(ix, f.path, f.type, locate(ix, f))
        if r.status != "extracted" and proposer is not None:
            proposal = proposer.propose(layer, f, r)
            if proposal is not None:
                r = _confirm(ix, f, proposal, proposer.name, r)
        results.append(r)
    return Extraction(spec.hash, layer.document_hash, layer.id, tuple(results))
