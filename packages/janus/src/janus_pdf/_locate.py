"""The five locators. Each finds every place a field's value is printed, or says why it found
none. Reading what they find, and deciding what that means, is `extract`'s job."""

from dataclasses import dataclass, field
from statistics import median

from janus_pdf._index import Index, normalize_label, rank
from janus_pdf.document import Line, Span, Table, TableCell, Word
from janus_pdf.spec import Cell, Field, Label, Records, Region, Section
from janus_pdf.values import clean


@dataclass(slots=True)
class Found:
    """What a locator found: the printed spans, or a reason and suggestions."""

    method: str
    spans: list[Span] = field(default_factory=list)
    reason: str = ""
    suggestions: tuple[str, ...] = ()
    hint: str = ""  # added to the message when the places found disagree


@dataclass(frozen=True, slots=True)
class Row:
    """One record's cells by key, and the row's first printed text, for stop labels."""

    cells: dict[str, Span]
    first: str


@dataclass(frozen=True, slots=True)
class Rows:
    """A records locator's result: the header it matched and the rows under it."""

    method: str  # "records" for a table, "records:layout" for printed rows without rules
    header: Span
    rows: tuple[Row, ...]


def locate(ix: Index, f: Field) -> Found:
    """Every place `f`'s value is printed, for any locator but `records`."""
    match f.locator:
        case Label() as loc:
            return _label(ix, f, loc)
        case Cell() as loc:
            return _cell(ix, loc)
        case Section() as loc:
            return _section(ix, f, loc)
        case Region() as loc:
            return _region(ix, loc)
        case Records():
            raise TypeError("records are located with locate_records")


def locate_records(ix: Index, loc: Records) -> Rows | None:
    """The rows under the first table row, or printed row, that holds every header."""
    return _table_records(ix, loc) or _line_records(ix, loc)


def _in_pages(ix: Index, f: Field, offset: int) -> bool:
    return f.pages is None or f.pages[0] <= ix.page_of(offset) <= f.pages[1]


def _trim(ix: Index, start: int, end: int) -> Span | None:
    text = ix.layer.text
    while start < end and (text[start].isspace() or text[start] in ":-\u2013"):
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return Span(start, end) if end > start else None


def _header_matches(cell: TableCell, column: str) -> bool:
    want = normalize_label(column)
    return any(normalize_label(h) == want for h in cell.header_path)


# --- label --------------------------------------------------------------------------------------


def _beside(ix: Index, label: Span) -> tuple[Span | None, bool]:
    """The value printed after a label that is not in a table: on the rest of its line, or the
    words to its right on the same row, or the line under it. The flag says whether the value
    is set off from the label by a colon or a column gap, rather than by a plain space."""
    text = ix.layer.text
    words = list(ix.words_between(label.start, label.end))
    if not words:
        return None, False
    lbox = words[-1].box
    height = lbox.y1 - lbox.y0
    line = ix.line_at(label.start)
    if line is not None and line.end > label.end:
        rest = _trim(ix, label.end, line.end)
        if rest:
            colon = text[label.end : rest.start].strip() in (":", "-", "\u2013")
            nxt = next(ix.words_between(rest.start, rest.end), None)
            gap = nxt is not None and nxt.box.x0 - lbox.x1 > 0.8 * height
            return rest, colon or gap
    page = next(p for p in ix.layer.pages if p.number == lbox.page)
    mid = (lbox.y0 + lbox.y1) / 2
    right = sorted(
        (
            w
            for w in ix.words
            if w.box.page == lbox.page
            and w.box.x0 >= lbox.x1 - 0.5
            and w.box.y0 <= mid <= w.box.y1
            and w.start >= label.end
        ),
        key=lambda w: w.box.x0,
    )
    picked: list[Word] = []
    edge = lbox.x1
    for w in right:
        if w.box.x0 - edge > (0.3 * page.width if not picked else 2.5 * height):
            break
        picked.append(w)
        edge = w.box.x1
    if picked:
        span = Span(min(w.start for w in picked), max(w.end for w in picked))
        return span, picked[0].box.x0 - lbox.x1 > 0.8 * height
    below = ix.line_at(line.end + 1) if line is not None else None
    if (
        below is not None
        and below.box.page == lbox.page
        and 0 <= below.box.y0 - lbox.y1 < 1.5 * height
        and min(below.box.x1, lbox.x1) > max(below.box.x0, words[0].box.x0)  # under the label
    ):
        return _trim(ix, below.start, below.end), True
    return None, False


def _label(ix: Index, f: Field, loc: Label) -> Found:
    found = Found("label")
    everywhere = [s for name in loc.names for s in ix.find_label(name)]
    labels = [s for s in everywhere if _in_pages(ix, f, s.start)]
    if not labels:
        names = " / ".join(map(repr, loc.names))
        if everywhere and f.pages is not None:
            pages = sorted({ix.page_of(s.start) for s in everywhere})
            first, last = f.pages
            allowed = f"page {first}" if first == last else f"pages {first}-{last}"
            found.reason = f"{names} begins a line only on page(s) {pages}, outside {allowed}"
            return found
        found.suggestions = tuple(s for name in loc.names for s in ix.suggestions(name))
        found.reason = f"no line or cell begins with {names}"
        return found
    partial: list[str] = []
    for span in labels:
        cell = ix.cell_at(span.start)
        if cell is not None:
            whole = ix.text(cell.start, cell.end)
            if normalize_label(whole) != normalize_label(ix.text(span.start, span.end)):
                # The label only begins a longer row label: offer it, do not read its row.
                partial.append(f"{clean(whole)!r} on page {ix.page_of(cell.start)} (longer cell)")
                continue
            row = [
                c
                for c in ix.by_table[cell.table_id]
                if c.row <= cell.row < c.row + c.row_span and c.col > cell.col
            ]
            if loc.column is not None:
                row = [c for c in row if _header_matches(c, loc.column)]
            else:
                row = [c for c in sorted(row, key=lambda c: c.col) if c.end > c.start][:1]
            found.spans += [v for c in row if (v := _trim(ix, c.start, c.end))]
            continue
        if loc.column is not None:
            continue
        value, set_off = _beside(ix, span)
        if value is None:
            continue
        if not set_off and f.type.kind == "text":
            # "Due" before "date": the printed label is probably longer than the spec's.
            line = ix.line_at(span.start)
            whole = clean(ix.text(span.start, line.end if line else value.end))
            partial.append(f"{whole!r} on page {ix.page_of(span.start)} (nothing sets it off)")
            continue
        found.spans.append(value)
    if not found.spans:
        pages = sorted({ix.page_of(s.start) for s in labels})
        where = f" under column {loc.column!r}" if loc.column else ""
        found.reason = f"the label is on page(s) {pages}, but no value is printed beside it{where}"
        found.suggestions = tuple(dict.fromkeys(partial))[:3]
    return found


# --- cell, section, region ----------------------------------------------------------------------


def _table(ix: Index, ref: str | int) -> Table | None:
    tables = ix.layer.tables
    if isinstance(ref, int):
        return tables[ref - 1] if 0 < ref <= len(tables) else None
    return next((t for t in tables if t.id == ref), None)


def _cell(ix: Index, loc: Cell) -> Found:
    table = _table(ix, loc.table)
    if table is None:
        return Found("cell", reason=f"no table {loc.table!r}; the layer has {len(ix.layer.tables)}")
    cells = ix.by_table[table.id]
    if isinstance(loc.row, int):
        rows = {loc.row}
    else:
        want = normalize_label(loc.row)
        rows = {
            c.row for c in cells if c.col == 0 and normalize_label(ix.text(c.start, c.end)) == want
        }
    found = Found("cell")
    for c in cells:
        if not any(c.row <= r < c.row + c.row_span for r in rows):
            continue
        if isinstance(loc.column, int):
            if c.col != loc.column:
                continue
        elif not _header_matches(c, loc.column):
            continue
        if value := _trim(ix, c.start, c.end):
            found.spans.append(value)
    if not found.spans:
        found.reason = (
            f"table {table.id} has no non-empty cell at row {loc.row!r}, column {loc.column!r}"
        )
    return found


def _parent(ix: Index, headings: tuple[Line, ...], i: int) -> str | None:
    """The text of the nearest heading above heading `i` that outranks it."""
    h = headings[i]
    parent = next((p for p in reversed(headings[:i]) if rank(p) > rank(h)), None)
    return clean(ix.text(parent.start, parent.end)) if parent else None


def _section(ix: Index, f: Field, loc: Section) -> Found:
    wanted = {normalize_label(h) for h in loc.heading}
    headings = ix.headings
    found = Found("section")
    parents: list[str | None] = []
    for i, h in enumerate(headings):
        if normalize_label(ix.text(h.start, h.end)) not in wanted or not _in_pages(ix, f, h.start):
            continue
        parent = _parent(ix, headings, i)
        if loc.under is not None and normalize_label(parent or "") != normalize_label(loc.under):
            continue
        nxt = next((n for n in headings[i + 1 :] if rank(n) >= rank(h)), None)
        if span := _trim(ix, h.end, nxt.start if nxt else len(ix.layer.text)):
            found.spans.append(span)
            parents.append(parent)
    if len(found.spans) > 1 and loc.under is None and all(parents):
        found.hint = "say which with `under:` " + " or ".join(
            map(repr, dict.fromkeys(p for p in parents if p))
        )
    if not found.spans:
        under = f" under {loc.under!r}" if loc.under else ""
        found.reason = f"no heading {' / '.join(map(repr, loc.heading))}{under}"
        if not headings:
            found.reason += "; the layer has no font sizes, so it has no headings"
    return found


def _region(ix: Index, loc: Region) -> Found:
    x0, y0, x1, y1 = loc.box
    inside = [
        w
        for w in ix.words
        if w.box.page == loc.page
        and x0 <= (w.box.x0 + w.box.x1) / 2 <= x1
        and y0 <= (w.box.y0 + w.box.y1) / 2 <= y1
    ]
    if not inside:
        return Found("region", reason=f"no words inside the box on page {loc.page}")
    return Found("region", [Span(min(w.start for w in inside), max(w.end for w in inside))])


# --- records ------------------------------------------------------------------------------------


def _table_records(ix: Index, loc: Records) -> Rows | None:
    wanted = [(k, normalize_label(h)) for k, h in loc.header]
    for table in ix.layer.tables:
        cells = ix.by_table[table.id]
        for r in range(table.rows):
            row = {normalize_label(ix.text(c.start, c.end)): c for c in cells if c.row == r}
            if not all(h in row for _, h in wanted):
                continue
            cols = {k: row[h].col for k, h in wanted}
            header = Span(min(c.start for c in row.values()), max(c.end for c in row.values()))
            rows = []
            for rr in range(r + 1, table.rows):
                body = {c.col: c for c in cells if c.row == rr}
                if not body:
                    continue
                spans = {
                    k: s
                    for k, col in cols.items()
                    if (c := body.get(col)) and (s := _trim(ix, c.start, c.end))
                }
                first = min(body.values(), key=lambda c: c.col)
                rows.append(Row(spans, clean(ix.text(first.start, first.end))))
            return Rows("records", header, tuple(rows))
    return None


def _visual_rows(words: list[Word]) -> list[list[Word]]:
    rows: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.box.y0, w.box.x0)):
        mid = (w.box.y0 + w.box.y1) / 2
        if rows and rows[-1][0].box.y0 <= mid <= rows[-1][0].box.y1:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w.box.x0) for r in rows]


def _line_records(ix: Index, loc: Records) -> Rows | None:
    """Records laid out without rules: the header is a printed row holding every column header,
    each column spans its header's width, and rows run until a gap or a stop label."""
    _, first_header = loc.header[0]
    for span in ix.find_label(first_header):
        if ix.cell_at(span.start):
            continue
        page = ix.page_of(span.start)
        start_word = next(ix.words_between(span.start, span.end))
        rows = _visual_rows([w for w in ix.words if w.box.page == page])
        header_row = next((r for r in rows if start_word in r), None)
        if header_row is None:
            continue
        # Find each header phrase among the header row's words, left to right.
        texts = [normalize_label(ix.text(w.start, w.end)) for w in header_row]
        extents: dict[str, tuple[float, float]] = {}
        claimed: set[int] = set()
        for key, header in loc.header:
            parts = normalize_label(header).split()
            for i in range(len(texts) - len(parts) + 1):
                if texts[i : i + len(parts)] == parts:
                    ws = header_row[i : i + len(parts)]
                    extents[key] = (ws[0].box.x0, ws[-1].box.x1)
                    claimed.update(range(i, i + len(parts)))
                    break
        if len(extents) != len(loc.header):
            continue
        # A printed column the spec leaves out still bounds its neighbours; its words are dropped.
        run: list[Word] = []
        for i, w in enumerate([*header_row, None]):
            if w is not None and i not in claimed:
                run.append(w)
            elif run:
                extents[f"\0{len(extents)}"] = (run[0].box.x0, run[-1].box.x1)
                run = []
        order = sorted(extents, key=lambda k: extents[k][0])
        # Column boundaries halfway between neighbouring headers; the first and last are open.
        bounds = {}
        for i, k in enumerate(order):
            lo = -1e9 if i == 0 else (extents[order[i - 1]][1] + extents[k][0]) / 2
            hi = 1e9 if i == len(order) - 1 else (extents[k][1] + extents[order[i + 1]][0]) / 2
            bounds[k] = (lo, hi)
        top = max(w.box.y1 for w in header_row)
        below = [r for r in rows if r[0].box.y0 >= top - 0.5]
        gap = 2.2 * median([r[0].box.y1 - r[0].box.y0 for r in below[:5]] or [10.0])
        out, last = [], top
        for r in below:
            if r[0].box.y0 - last > gap:
                break
            cells: dict[str, list[Word]] = {}
            for w in r:
                mid = (w.box.x0 + w.box.x1) / 2
                key = next(k for k in order if bounds[k][0] <= mid < bounds[k][1])
                if not key.startswith("\0"):
                    cells.setdefault(key, []).append(w)
            spans = {
                k: Span(min(w.start for w in ws), max(w.end for w in ws)) for k, ws in cells.items()
            }
            out.append(Row(spans, clean(" ".join(ix.text(w.start, w.end) for w in r))))
            last = max(w.box.y1 for w in r)
        header = Span(min(w.start for w in header_row), max(w.end for w in header_row))
        return Rows("records:layout", header, tuple(out))
    return None
