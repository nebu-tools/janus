"""The five locators. Each finds every place a field's value is printed, or says why it found
none. Reading what they find, and deciding what that means, is `extract`'s job.

A place is the exact words of one printed value, as spans of the layer text in reading order:
one span when the words follow one another, several when other words are printed between them
(a region beside another column, a description wrapped under a quantity). Locators read the layer
through a `View`, so a field's pages apply to all of them alike.
"""

import re
from dataclasses import dataclass, field
from statistics import median

from janus_pdf._index import View, normalize_label, rank
from janus_pdf.document import Box, Line, Span, Table, TableCell, Word
from janus_pdf.document.layout import Rect
from janus_pdf.spec import Cell, Field, Label, Records, Region, Section
from janus_pdf.values import clean

Place = tuple[Span, ...]


@dataclass(slots=True)
class Found:
    """What a locator found: the places a value is printed, or a reason and suggestions."""

    method: str
    places: list[Place] = field(default_factory=list)
    reason: str = ""
    suggestions: tuple[str, ...] = ()
    hint: str = ""  # added to the message when the places found disagree
    note: str = ""  # added to the message when the value is extracted


@dataclass(frozen=True, slots=True)
class Row:
    """One record's cells by key, the row's first printed text, and its page."""

    cells: dict[str, Place]
    first: str
    page: int


@dataclass(frozen=True, slots=True)
class Rows:
    """A records locator's result: the header it matched and the rows under it.

    `incomplete` says why the rows may not be all of them (the header printed again on another
    page, a table that carries itself forward past its last page); `ambiguous` says which
    printed line no declaration gives to a record. Either one means the rows are not a value.
    """

    method: str  # "records" for a table, "records:layout" for printed rows without rules
    header: Span
    rows: tuple[Row, ...]
    pages: tuple[int, ...] = ()
    skipped: tuple[str, ...] = ()  # carried-forward and continued lines, left out
    furniture: tuple[str, ...] = ()  # running heads and feet left out of a continued table
    incomplete: str = ""
    ambiguous: str = ""


def locate(view: View, f: Field) -> Found:
    """Every place `f`'s value is printed, for any locator but `records`."""
    match f.locator:
        case Label() as loc:
            return _label(view, f, loc)
        case Cell() as loc:
            return _cell(view, loc)
        case Section() as loc:
            return _section(view, loc)
        case Region() as loc:
            return _region(view, loc)
        case Records():
            raise TypeError("records are located with locate_records")


def locate_records(view: View, loc: Records) -> Rows | None:
    """The rows under the first table row, or printed row, that holds every header."""
    reader = _table_records(view, loc) or _line_records(view, loc)
    return None if reader is None else _follow(view, loc, reader)


def _strip(view: View, start: int, end: int) -> Span | None:
    """[start, end) without the whitespace around it. A value's own characters are kept."""
    text = view.layer.text
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return Span(start, end) if end > start else None


def _under(cells: list[TableCell], column: str) -> set[int]:
    """The grid columns headed `column`. A cell is under the header when it covers one of them,
    so a merged cell spanning two columns is under both headers."""
    want = normalize_label(column)
    return {
        c.col
        for c in cells
        if c.col_span == 1 and any(normalize_label(h) == want for h in c.header_path)
    }


def _covers(cell: TableCell, cols: set[int]) -> bool:
    return any(cell.col <= k < cell.col + cell.col_span for k in cols)


# --- label --------------------------------------------------------------------------------------


def _after_label(view: View, end: int, line_end: int) -> tuple[Span | None, bool]:
    """The rest of a line after a label, without the label's separator, and whether there was
    one. The separator is a colon, or a dash with a space after it; a dash or minus sign right
    before a value ("Amount: -123", "Amount -123") is the value's sign and stays."""
    text = view.layer.text
    i = end
    while i < line_end and text[i].isspace():
        i += 1
    separated = False
    if i < line_end and (
        text[i] == ":"
        or (text[i] in "-\u2013\u2014" and (i + 1 == line_end or text[i + 1].isspace()))
    ):
        separated = True
        i += 1
    return _strip(view, i, line_end), separated


def _beside(view: View, label: Span) -> tuple[Place | None, bool]:
    """The value printed after a label that is not in a table: on the rest of its line, or the
    words to its right on the same row, or the line under it. The flag says whether the value
    is set off from the label by a separator or a column gap, rather than by a plain space."""
    words = list(view.words_between(label.start, label.end))
    if not words:
        return None, False
    lbox = words[-1].box
    height = lbox.y1 - lbox.y0
    line = view.line_at(label.start)
    if line is not None and line.end > label.end:
        rest, separated = _after_label(view, label.end, line.end)
        if rest:
            nxt = next(view.words_between(rest.start, rest.end), None)
            gap = nxt is not None and nxt.box.x0 - lbox.x1 > 0.8 * height
            return (rest,), separated or gap
    page = next(p for p in view.layer.pages if p.number == lbox.page)
    mid = (lbox.y0 + lbox.y1) / 2
    right = sorted(
        (
            w
            for w in view.words
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
        return view.place(picked), picked[0].box.x0 - lbox.x1 > 0.8 * height
    below = view.line_at(line.end + 1) if line is not None else None
    if (
        below is not None
        and below.box.page == lbox.page
        and 0 <= below.box.y0 - lbox.y1 < 1.5 * height
        and min(below.box.x1, lbox.x1) > max(below.box.x0, words[0].box.x0)  # under the label
        and (value := _strip(view, below.start, below.end))
    ):
        return (value,), True
    return None, False


def _label(view: View, f: Field, loc: Label) -> Found:
    found = Found("label")
    labels = [s for name in loc.names for s in view.find_label(name)]
    if not labels:
        names = " / ".join(map(repr, loc.names))
        everywhere = [s for name in loc.names for s in view.index.find_label(name)]
        if everywhere and view.pages is not None:
            pages = sorted({view.page_of(s.start) for s in everywhere})
            first, last = view.pages
            allowed = f"page {first}" if first == last else f"pages {first}-{last}"
            found.reason = f"{names} begins a line only on page(s) {pages}, outside {allowed}"
            return found
        found.suggestions = tuple(s for name in loc.names for s in view.suggestions(name))
        found.reason = f"no line or cell begins with {names}"
        return found
    partial: list[str] = []
    for span in labels:
        cell = view.cell_at(span.start)
        if cell is not None:
            whole = view.text(cell.start, cell.end)
            if normalize_label(whole) != normalize_label(view.text(span.start, span.end)):
                # The label only begins a longer row label: offer it, do not read its row.
                partial.append(f"{clean(whole)!r} on page {view.page_of(cell.start)} (longer cell)")
                continue
            row = [
                c
                for c in view.by_table[cell.table_id]
                if c.row <= cell.row < c.row + c.row_span and c.col > cell.col
            ]
            if loc.column is not None:
                under = _under(view.by_table[cell.table_id], loc.column)
                row = [c for c in row if _covers(c, under)]
            else:
                row = [c for c in sorted(row, key=lambda c: c.col) if c.end > c.start][:1]
            found.places += [(v,) for c in row if (v := _strip(view, c.start, c.end))]
            continue
        if loc.column is not None:
            continue
        value, set_off = _beside(view, span)
        if value is None:
            continue
        if not set_off and f.type.kind == "text":
            # "Due" before "date": the printed label is probably longer than the spec's.
            line = view.line_at(span.start)
            whole = clean(view.text(span.start, line.end if line else value[-1].end))
            partial.append(f"{whole!r} on page {view.page_of(span.start)} (nothing sets it off)")
            continue
        found.places.append(value)
    if not found.places:
        pages = sorted({view.page_of(s.start) for s in labels})
        where = f" under column {loc.column!r}" if loc.column else ""
        found.reason = f"the label is on page(s) {pages}, but no value is printed beside it{where}"
        found.suggestions = tuple(dict.fromkeys(partial))[:3]
    return found


# --- cell, section, region ----------------------------------------------------------------------


def _table(view: View, ref: str | int) -> Table | None:
    tables = view.tables
    if isinstance(ref, int):
        return tables[ref - 1] if 0 < ref <= len(tables) else None
    return next((t for t in tables if t.id == ref), None)


def _cell(view: View, loc: Cell) -> Found:
    """The cells at a row and a column. A merged cell is at every row and column it spans, and a
    row label that spans several rows names all of them."""
    table = _table(view, loc.table)
    if table is None:
        where = "" if view.pages is None else " on the field's pages"
        return Found(
            "cell", reason=f"no table {loc.table!r}; the layer has {len(view.tables)}{where}"
        )
    cells = view.by_table[table.id]
    if isinstance(loc.row, int):
        rows = {loc.row}
    else:
        want = normalize_label(loc.row)
        rows = {
            r
            for c in cells
            if c.col == 0 and normalize_label(view.text(c.start, c.end)) == want
            for r in range(c.row, c.row + c.row_span)
        }
    found = Found("cell")
    empty = 0
    under = _under(cells, loc.column) if isinstance(loc.column, str) else set()
    for c in cells:
        if not any(c.row <= r < c.row + c.row_span for r in rows):
            continue
        if isinstance(loc.column, int):
            if not c.col <= loc.column < c.col + c.col_span:
                continue
        elif not _covers(c, under):
            continue
        if value := _strip(view, c.start, c.end):
            found.places.append((value,))
        else:
            empty += 1
    if not found.places:
        what = "is empty" if empty else "is not in the table"
        found.reason = f"table {table.id}'s cell at row {loc.row!r}, column {loc.column!r} {what}"
    return found


def _parent(view: View, headings: tuple[Line, ...], i: int) -> str | None:
    """The text of the nearest heading above heading `i` that outranks it."""
    h = headings[i]
    parent = next((p for p in reversed(headings[:i]) if rank(p) > rank(h)), None)
    return clean(view.text(parent.start, parent.end)) if parent else None


def _section(view: View, loc: Section) -> Found:
    """The text under each matching heading on the field's pages, up to the next heading printed
    at least as large or the end of the field's last page. Where the text runs over a page
    break, the running heads and feet inside it are left out, and the note says which."""
    wanted = {normalize_label(h) for h in loc.heading}
    headings = view.headings
    found = Found("section")
    parents: list[str | None] = []
    notes: list[str] = []
    for i, h in enumerate(headings):
        if normalize_label(view.text(h.start, h.end)) not in wanted:
            continue
        parent = _parent(view, headings, i)
        if loc.under is not None and normalize_label(parent or "") != normalize_label(loc.under):
            continue
        nxt = next((n for n in headings[i + 1 :] if rank(n) >= rank(h)), None)
        end = nxt.start if nxt else view.end
        if nxt is None and view.end < len(view.layer.text):
            beyond = next(
                (n for n in view.index.headings if n.start >= view.end and rank(n) >= rank(h)),
                None,
            )
            if view.text(view.end, beyond.start if beyond else len(view.layer.text)).strip():
                last = view.page_of(view.end - 1)
                notes.append(f"the section may go on after page {last}, outside the field's pages")
        place, left = _body(view, h.end, end)
        if place:
            found.places.append(place)
            parents.append(parent)
            notes += left
    found.note = "; ".join(dict.fromkeys(notes))
    if len(found.places) > 1:
        distinct = list(dict.fromkeys(parents))
        if loc.under is None and None not in distinct and len(distinct) == len(parents):
            found.hint = "say which with `under:` " + " or ".join(map(repr, distinct))
        else:
            # `under` cannot tell them apart: the same heading under the same parent.
            twice = ", ".join(sorted({repr(p) for p in parents if parents.count(p) > 1}))
            found.hint = (
                f"the heading is printed more than once under {twice or 'no parent'}, which "
                "`under:` cannot tell apart; narrow it with `pages:` or take it with a `region`"
            )
    if not found.places:
        under = f" under {loc.under!r}" if loc.under else ""
        found.reason = f"no heading {' / '.join(map(repr, loc.heading))}{under}"
        if not view.index.headings:
            found.reason += "; the layer has no font sizes, so it has no headings"
    return found


def _body(view: View, start: int, end: int) -> tuple[Place, list[str]]:
    """[start, end) as a place, without the running heads and feet inside it when it runs over
    a page break, and a note for each line left out."""
    if view.page_of(start) == view.page_of(max(start, end - 1)):
        span = _strip(view, start, end)
        return ((span,) if span else ()), []
    out = sorted(
        (ln for ln in view.index.layer.lines if ln.start in view.index.furniture),
        key=lambda ln: ln.start,
    )
    out = [ln for ln in out if start <= ln.start and ln.end <= end]
    spans: list[Span] = []
    at = start
    for ln in [*out, None]:
        stop = ln.start if ln else end
        if span := _strip(view, at, stop):
            spans.append(span)
        if ln:
            at = ln.end
    left: dict[str, list[int]] = {}
    for ln in out:
        left.setdefault(clean(view.text(ln.start, ln.end)), []).append(ln.box.page)
    notes = [f"left out the running head or foot {t!r} on {_on(ps)}" for t, ps in left.items()]
    return tuple(spans), notes


def _region(view: View, loc: Region) -> Found:
    """The words whose centres are inside the box, and only those, in reading order."""
    x0, y0, x1, y1 = loc.box
    inside = [
        w
        for w in view.words
        if w.box.page == loc.page
        and x0 <= (w.box.x0 + w.box.x1) / 2 <= x1
        and y0 <= (w.box.y0 + w.box.y1) / 2 <= y1
    ]
    if not inside:
        return Found("region", reason=f"no words inside the box on page {loc.page}")
    return Found("region", [view.place(inside)])


# --- records: what the kinds of table share -----------------------------------------------------
#
# A table's rows become printed lines (`_Line`): the words in each column, the line's first text
# and the whole line. Both kinds of table are read by a `_Reader` and go through the same steps in
# `_follow`: carried-forward lines are left out, a stop label ends the rows, and the rows go on
# to the next page only when the spec declares that the table runs over pages.

_CARRIED = re.compile(
    r"\(?(?:continued|cont(?:'|\u2019)?d\.?|(?:balance )?(?:carried|brought) (?:forward|over)"
    r"|c/f|b/f)\)?[:.]?"
)
_CONTINUED = re.compile(
    r"\b(?:continued|cont(?:'|\u2019)?d|(?:carried|brought) (?:forward|over))\b"
)
_ALIGNED = 1.5  # points: column edges this close are the same column
_AGAIN = "the header, or rows under the same columns, is printed again on"


@dataclass(slots=True)
class _Line:
    page: int
    cells: dict[str, list[Word]]
    first: str  # the text in the leftmost column
    text: str  # the whole printed line


def _on(pages: list[int]) -> str:
    return f"page {pages[0]}" if len(pages) == 1 else f"pages {', '.join(map(str, pages))}"


def _range(first: int, last: int) -> str:
    return str(first) if first == last else f"{first}-{last}"


def _top(view: View, box: Box) -> float:
    return view.upright(box)[1]


def _free(view: View, line: Line) -> bool:
    """A line a page may print above a continued table: a possible running head, or a
    "continued" line."""
    if line.start in view.index.furniture:
        return True
    return bool(_CONTINUED.search(normalize_label(view.text(line.start, line.end))))


def _furniture(view: View, page: int, loc: Records) -> list[Line]:
    """The possible running heads and feet of `page`, without lines that print nothing but
    header words: a header repeated at the top of every page looks like a running head."""
    headers = {t for _, h in loc.header for t in normalize_label(h).split()}
    return [
        ln
        for ln in view.lines_on(page)
        if ln.start in view.index.furniture
        and not set(normalize_label(view.text(ln.start, ln.end)).split()) <= headers
    ]


def _starts(first: str, stops: list[str]) -> bool:
    n = normalize_label(first)
    return any(n.startswith(s) and (len(n) == len(s) or not n[len(s)].isalnum()) for s in stops)


def _carried(line: _Line) -> bool:
    first = normalize_label(line.first)
    return bool(_CARRIED.fullmatch(first) or _CONTINUED.search(first))


def _cut(lines: list[_Line], loc: Records, skipped: list[str]) -> tuple[list[_Line], bool, bool]:
    """`lines` without carried-forward lines and up to a stop label; whether a stop label ended
    them, and whether the last line carries the table forward."""
    stops = [normalize_label(s) for s in loc.stop]
    out = []
    for line in lines:
        if _starts(line.first, stops):
            return out, True, False
        if _carried(line):
            skipped.append(f"{clean(line.first)!r} on page {line.page}")
            continue
        out.append(line)
    return out, False, bool(lines) and _carried(lines[-1])


def _rows(view: View, groups: list[list[_Line]], keys: list[str]) -> tuple[Row, ...]:
    return tuple(
        Row(
            {
                k: view.place(w for line in group for w in line.cells.get(k, ()))
                for k in keys
                if any(k in line.cells for line in group)
            },
            group[0].first,
            group[0].page,
        )
        for group in groups
    )


class _Reader:
    """One kind of table, found on its first page: its lines there, and whether another page
    shows the header again or opens with rows under the same columns."""

    method: str
    page: int  # the page the header is printed on
    header: Span
    top: float  # the top of the header, in the page's reading frame

    def __init__(self, view: View, loc: Records) -> None:
        self.view, self.loc = view, loc
        self._matches: dict[int, list[_Line] | None] = {}

    def lines(self, drop: bool) -> list[_Line]:
        """The lines under the header on its page; `drop` leaves the possible running heads
        and feet out."""
        raise NotImplementedError

    def match(self, page: int) -> list[_Line] | None:
        """The lines on `page` that would continue the table, or None when the page neither
        shows the header again nor opens with rows under the same columns."""
        if page not in self._matches:
            self._matches[page] = self._match(page)
        return self._matches[page]

    def _match(self, page: int) -> list[_Line] | None:
        raise NotImplementedError

    def group(self, lines: list[_Line]) -> tuple[list[list[_Line]], str]:
        """The lines as records, or why a line cannot be given to one."""
        return [[line] for line in lines], ""

    def left_out(self, page: int) -> list[str]:  # noqa: ARG002 - a cell is never furniture
        """The text left out of the table on `page` as running heads and feet."""
        return []


def _follow(view: View, loc: Records, reader: _Reader) -> Rows:
    """The rows of the table `reader` found, on its page and, when the spec declares that the
    table runs over pages, on each following page that continues it."""
    keys = [k for k, _ in loc.header]
    later = [n for n in view.numbers if n > reader.page]
    first = reader.page
    _, stopped, _ = _cut(reader.lines(False), loc, [])
    flows = (
        loc.continues and not stopped and first + 1 in later and reader.match(first + 1) is not None
    )
    skipped: list[str] = []
    lines, stopped, carried = _cut(reader.lines(flows), loc, skipped)
    pages = [first]
    while flows and not stopped and pages[-1] + 1 in later:
        more = reader.match(pages[-1] + 1)
        if more is None:
            break
        found, stopped, carried = _cut(more, loc, skipped)
        lines += found
        pages.append(pages[-1] + 1)
    last = pages[-1]
    again = [n for n in later if n > last and reader.match(n) is not None]
    incomplete = ""
    if again and not loc.continues:
        incomplete = (
            f"{_AGAIN} {_on(again)}; if the table runs over pages, declare it with "
            f"`continues: true`; if it does not, keep the field to page {first} with "
            f"`pages: {first}`"
        )
    elif again:
        how = "at a `stop:` label" if stopped else f"because page {last + 1} does not continue it"
        incomplete = (
            f"the table ends on page {last} {how}, but {_AGAIN} {_on(again)}; keep the field to "
            f"the table's pages with `pages: {_range(first, last)}`"
        )
    elif carried and not stopped:
        nxt = last + 1
        if not view.layer.pages or nxt > view.layer.pages[-1].number:
            why = f"page {last} is the document's last page"
        elif not view.on(nxt):
            why = f"page {nxt} is outside the field's pages"
        elif not loc.continues:
            why = "the spec does not declare `continues: true`"
        else:
            why = (
                f"page {nxt} neither repeats the header nor opens with rows under the same columns"
            )
        incomplete = f"its last line on page {last} carries the table forward, but {why}"
    left: dict[str, list[int]] = {}
    if len(pages) > 1:
        for n in pages:
            for text in reader.left_out(n):
                left.setdefault(clean(text), []).append(n)
    groups, ambiguous = reader.group(lines)
    return Rows(
        reader.method,
        reader.header,
        _rows(view, groups, keys),
        tuple(pages),
        tuple(skipped),
        tuple(f"{text!r} on {_on(ns)}" for text, ns in left.items()),
        incomplete,
        ambiguous,
    )


# --- records in tables --------------------------------------------------------------------------


def _header_row(
    view: View, table: Table, wanted: list[tuple[str, str]]
) -> tuple[int, dict[str, int], Span] | None:
    cells = view.by_table[table.id]
    for r in range(table.rows):
        row = {normalize_label(view.text(c.start, c.end)): c for c in cells if c.row == r}
        if all(h in row for _, h in wanted):
            printed = [c for c in row.values() if c.end > c.start]
            header = Span(min(c.start for c in printed), max(c.end for c in printed))
            return r, {k: row[h].col for k, h in wanted}, header
    return None


def _table_lines(view: View, table: Table, start: int, cols: dict[str, int]) -> list[_Line]:
    cells = view.by_table[table.id]
    lines = []
    for r in range(start, table.rows):
        row = [c for c in cells if c.row <= r < c.row + c.row_span]
        if not row:
            continue
        words = {
            k: ws
            for k, col in cols.items()
            for c in row
            if c.col <= col < c.col + c.col_span
            and (ws := list(view.words_between(c.start, c.end)))
        }
        printed = sorted((c for c in row if c.end > c.start and c.row == r), key=lambda c: c.col)
        texts = [view.text(c.start, c.end) for c in printed]
        lines.append(_Line(table.page, words, texts[0] if texts else "", " ".join(texts)))
    return lines


def _edges(view: View, table: Table) -> list[float]:
    cells = [c for c in view.by_table[table.id] if c.col_span == 1]
    lefts = {c.col: view.upright(c.box)[0] for c in sorted(cells, key=lambda c: -c.row)}
    return [lefts.get(col, float("nan")) for col in range(table.cols)] + [
        view.upright(table.box)[2]
    ]


class _Ruled(_Reader):
    method = "records"

    def __init__(self, view: View, loc: Records, table: Table, found) -> None:
        super().__init__(view, loc)
        self.table = table
        self.start, self.cols, self.header = found[0] + 1, found[1], found[2]
        self.page = table.page
        self.top = _top(view, table.box)
        self.wanted = [(k, normalize_label(h)) for k, h in loc.header]

    def lines(self, drop: bool) -> list[_Line]:  # noqa: ARG002 - nothing in a cell is furniture
        return _table_lines(self.view, self.table, self.start, self.cols)

    def _match(self, page: int) -> list[_Line] | None:
        view = self.view
        tables = [t for t in view.tables if t.page == page]
        for t in tables:
            if found := _header_row(view, t, self.wanted):
                return _table_lines(view, t, found[0] + 1, found[1])
        if not tables:
            return None
        nxt = tables[0]
        top = _top(view, nxt.box)
        if any(
            not _free(view, ln) for ln in view.lines_on(page) if view.upright(ln.box)[3] <= top + 1
        ):
            return None  # the page does not open with the table
        a, b = _edges(view, self.table), _edges(view, nxt)
        if len(a) == len(b) and all(abs(x - y) <= _ALIGNED for x, y in zip(a, b, strict=True)):
            titles = {c.row for c in view.by_table[nxt.id] if c.role == "title"}
            return _table_lines(view, nxt, len(titles), self.cols)
        return None


def _table_records(view: View, loc: Records) -> _Reader | None:
    wanted = [(k, normalize_label(h)) for k, h in loc.header]
    for table in view.tables:
        if found := _header_row(view, table, wanted):
            return _Ruled(view, loc, table, found)
    return None


# --- records printed without a table ------------------------------------------------------------
#
# Geometry here is in each page's reading frame (`View.upright`), so a table printed on a page
# the viewer turns is read along its rows.


@dataclass(frozen=True, slots=True)
class _Columns:
    order: list[str]  # keys left to right; "\0n" for a printed column the spec leaves out
    bounds: dict[str, tuple[float, float]]
    top: float  # the bottom of the header row

    def of(self, x0: float, x1: float) -> str:
        """The column a word from `x0` to `x1` is printed in."""
        mid = (x0 + x1) / 2
        return next(k for k in self.order if self.bounds[k][0] <= mid < self.bounds[k][1])


_Printed = list[tuple[Word, Rect]]  # one printed row: its words and their upright boxes


def _visual_rows(view: View, words: list[Word]) -> list[_Printed]:
    rows: list[_Printed] = []
    boxed = sorted(((w, view.upright(w.box)) for w in words), key=lambda wb: (wb[1][1], wb[1][0]))
    for w, b in boxed:
        mid = (b[1] + b[3]) / 2
        if rows and rows[-1][0][1][1] <= mid <= rows[-1][0][1][3]:
            rows[-1].append((w, b))
        else:
            rows.append([(w, b)])
    return [sorted(r, key=lambda wb: wb[1][0]) for r in rows]


def _split(
    view: View, page: int, loc: Records, cols: _Columns | None
) -> tuple[list[_Printed], list[_Printed]]:
    """The printed rows of `page`, and, given the table's columns, the rows left out of them as
    possible running heads and feet: rows printed wholly in such lines that leave a column
    empty. A row that fills every column is a record, wherever it stands."""
    rows = _visual_rows(view, view.words_on(page))
    if cols is None:
        return rows, []
    spans = [(ln.start, ln.end) for ln in _furniture(view, page, loc)]
    keys = {k for k, _ in loc.header}
    kept, left = [], []
    for r in rows:
        furniture = all(any(s <= w.start < e for s, e in spans) for w, _ in r)
        full = keys <= {cols.of(b[0], b[2]) for _, b in r}
        (left if furniture and not full else kept).append(r)
    return kept, left


def _page_rows(view: View, page: int, loc: Records, cols: _Columns | None) -> list[_Printed]:
    """The printed rows of `page`; given the table's columns, without its running heads and
    feet."""
    return _split(view, page, loc, cols)[0]


def _columns(view: View, row: _Printed, loc: Records) -> _Columns | None:
    """The columns a printed header row sets, when it holds every header of `loc`."""
    texts = [normalize_label(view.text(w.start, w.end)) for w, _ in row]
    extents: dict[str, tuple[float, float]] = {}
    claimed: set[int] = set()
    for key, header in loc.header:
        parts = normalize_label(header).split()
        for i in range(len(texts) - len(parts) + 1):
            if texts[i : i + len(parts)] == parts and not claimed & set(range(i, i + len(parts))):
                extents[key] = (row[i][1][0], row[i + len(parts) - 1][1][2])
                claimed.update(range(i, i + len(parts)))
                break
    if len(extents) != len(loc.header):
        return None
    # A printed column the spec leaves out still bounds its neighbours; its words are dropped.
    run: list[Rect] = []
    for i, wb in enumerate([*row, None]):
        if wb is not None and i not in claimed:
            run.append(wb[1])
        elif run:
            extents[f"\0{len(extents)}"] = (run[0][0], run[-1][2])
            run = []
    order = sorted(extents, key=lambda k: extents[k][0])
    # Column boundaries halfway between neighbouring headers; the first and last are open.
    bounds = {}
    for i, k in enumerate(order):
        lo = -1e9 if i == 0 else (extents[order[i - 1]][1] + extents[k][0]) / 2
        hi = 1e9 if i == len(order) - 1 else (extents[k][1] + extents[order[i + 1]][0]) / 2
        bounds[k] = (lo, hi)
    return _Columns(order, bounds, max(b[3] for _, b in row))


@dataclass(slots=True)
class _Laid:
    line: _Line
    edges: dict[str, tuple[float, float]]  # where each column's words start and end


def _layout_lines(view: View, rows: list[_Printed], cols: _Columns, page: int) -> list[_Laid]:
    """The printed lines under a header row, up to a gap of more than 2.2 line heights."""
    below = [r for r in rows if r[0][1][1] >= cols.top - 0.5]
    gap = 2.2 * median([r[0][1][3] - r[0][1][1] for r in below[:5]] or [10.0])
    out, last = [], cols.top
    for r in below:
        if r[0][1][1] - last > gap:
            break
        printed: dict[str, _Printed] = {}
        for w, b in r:
            printed.setdefault(cols.of(b[0], b[2]), []).append((w, b))
        # The first text is the leftmost column's, printed or left out of the spec: a stop label
        # such as "Subtotal" may stand in a column the spec does not name.
        leftmost = min(printed.values(), key=lambda ws: ws[0][1][0])
        first = " ".join(view.text(w.start, w.end) for w, _ in leftmost)
        text = " ".join(view.text(w.start, w.end) for w, _ in r)
        cells = {k: [w for w, _ in ws] for k, ws in printed.items() if not k.startswith("\0")}
        edges = {k: (ws[0][1][0], ws[-1][1][2]) for k, ws in printed.items()}
        out.append(_Laid(_Line(page, cells, first, text), edges))
        last = max(b[3] for _, b in r)
    return out


def _aligned(line: _Laid, before: list[_Laid]) -> bool:
    """Whether every column `line` fills starts or ends where the same column does in the lines
    `before`, in at least two columns."""
    if len(line.line.cells) < 2:
        return False
    for key in line.line.cells:
        x0, x1 = line.edges[key]
        edges = [b.edges[key] for b in before if key in b.line.cells]
        if not any(abs(x0 - a) <= _ALIGNED or abs(x1 - b) <= _ALIGNED for a, b in edges):
            return False
    return True


def _partial(line: _Line, keys: list[str]) -> str:
    filled = [k for k in keys if k in line.cells]
    empty = [k for k in keys if k not in line.cells]
    return (
        f"the line {clean(line.text)!r} on page {line.page} prints only "
        f"{', '.join(filled) or 'nothing'}, not {', '.join(empty)}"
    )


class _Layout(_Reader):
    method = "records:layout"

    def __init__(
        self, view: View, loc: Records, heads: dict[int, list[int]], page: int, row, cols
    ) -> None:
        super().__init__(view, loc)
        self.heads, self.page, self.row, self.cols = heads, page, row, cols
        self.header = Span(min(w.start for w, _ in row), max(w.end for w, _ in row))
        self.top = min(b[1] for _, b in row)
        self._first: list[_Laid] | None = None

    def lines(self, drop: bool) -> list[_Line]:
        rows = _page_rows(self.view, self.page, self.loc, self.cols if drop else None)
        return [x.line for x in _layout_lines(self.view, rows, self.cols, self.page)]

    def left_out(self, page: int) -> list[str]:
        _, left = _split(self.view, page, self.loc, self.cols)
        view = self.view
        return [
            " ".join(view.text(w.start, w.end) for w, _ in r)
            for r in left
            if page != self.page or r[0][1][1] >= self.top
        ]

    def _match(self, page: int) -> list[_Line] | None:
        view, loc = self.view, self.loc
        rows = _page_rows(view, page, loc, self.cols)
        if not rows:
            return None
        found = _header(view, loc, rows, self.heads.get(page, []))
        if found is not None:
            return [x.line for x in _layout_lines(view, rows, found[1], page)]
        if self._first is None:
            rows1 = _page_rows(view, self.page, loc, None)
            self._first = _layout_lines(view, rows1, self.cols, self.page)
        cols = _Columns(self.cols.order, self.cols.bounds, rows[0][0][1][1] - 0.5)
        probe = _layout_lines(view, rows, cols, page)
        if probe and _aligned(probe[0], self._first):
            return [x.line for x in probe]
        return None

    def group(self, lines: list[_Line]) -> tuple[list[list[_Line]], str]:
        """Printed lines as records. Without `filled`, every line must fill every column. With
        it, a line that fills the named columns starts a record (`first`) or ends one (`last`),
        and every other line joins that record."""
        loc = self.loc
        keys = [k for k, _ in loc.header]
        marks = set(loc.filled)
        if not marks:
            for line in lines:
                if set(line.cells) != set(keys):
                    lacking = [k for k in keys if k not in line.cells] or keys
                    return [], (
                        f"{_partial(line, keys)}, so it may continue a record or be one of its "
                        "own; say which columns every record fills on its first line with "
                        f"`filled: {{first: [{', '.join(lacking)}]}}` (or on its last line with "
                        "`filled: {last: [...]}`)"
                    )
            return [[line] for line in lines], ""
        groups: list[list[_Line]] = []
        pending: list[_Line] = []
        for line in lines:
            marked = marks <= set(line.cells)
            if loc.filled_on == "first":
                if marked:
                    groups.append([line])
                elif groups:
                    groups[-1].append(line)
                else:
                    return [], (
                        f"{_partial(line, keys)} and comes before the first line that fills "
                        f"{', '.join(loc.filled)}, so it belongs to no record"
                    )
            else:
                pending.append(line)
                if marked:
                    groups.append(pending)
                    pending = []
        if pending:
            return [], (
                f"{_partial(pending[0], keys)} and comes after the last line that fills "
                f"{', '.join(loc.filled)}, so it belongs to no record"
            )
        return groups, ""


def _header(
    view: View, loc: Records, rows: list[_Printed], starts: list[int]
) -> tuple[_Printed, _Columns] | None:
    """The printed row holding every header, among the rows that hold one of `starts` (where
    the first header is printed), and its columns."""
    for start in starts:
        row = next((r for r in rows if any(w.start == start for w, _ in r)), None)
        if row is not None and (cols := _columns(view, row, loc)) is not None:
            return row, cols
    return None


def _line_records(view: View, loc: Records) -> _Reader | None:
    """Records laid out without rules: the header is a printed row holding every column header,
    each column spans its header's width, and rows run until a gap or a stop label."""
    heads: dict[int, list[int]] = {}
    for span in view.find_label(loc.header[0][1]):
        if not view.cell_at(span.start):
            heads.setdefault(view.page_of(span.start), []).append(span.start)
    for page, starts in heads.items():
        found = _header(view, loc, _page_rows(view, page, loc, None), starts)
        if found is not None:
            return _Layout(view, loc, heads, page, *found)
    return None
