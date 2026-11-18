"""The five locators. Each finds every place a field's value is printed, or says why it found
none. Reading what they find, and deciding what that means, is `extract`'s job.

A place is the exact words of one printed value, as spans of the layer text in reading order:
one span when the words follow one another, several when other words are printed between them
(a region beside another column, a description wrapped under a quantity). Locators read the layer
through a `View`, so a field's pages apply to all of them alike.
"""

from dataclasses import dataclass, field, replace

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
    """One record's cells by key, its printed lines' text, and its page."""

    cells: dict[str, Place]
    text: str
    page: int


@dataclass(frozen=True, slots=True)
class Rows:
    """A records locator's result: the header it matched and the rows under it.

    `notes` says what was left out of the rows and where the table ended. `incomplete` says why
    the rows may not be all of them, or may hold another table's rows (the header printed again
    on a page the table does not reach, a line set like the header, a title over a continued
    table); `ambiguous` says which printed line no declaration gives to a record. Either one
    means the rows are not a value.
    """

    method: str  # "records" for a table, "records:layout" for printed rows without rules
    header: Span
    rows: tuple[Row, ...]
    pages: tuple[int, ...] = ()
    notes: tuple[str, ...] = ()
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
# A table's rows become printed lines (`_Line`). Both kinds of table are read by a `_Reader` and
# go through the same steps in `_follow`: a `stop:` row ends the table, `skip:` rows and the
# header printed again are left out, a line that does not fit the columns ends a table without
# rules, and the table goes on to the next page only in the form `continues:` declares. The
# words of a row are compared only with the spec's own labels and headers; vertical spacing
# decides nothing.

_ALIGNED = 1.5  # points: edges this close are the same edge
_AGAIN = "the header, or rows on the same column edges, is printed again on"

_Edges = dict[str, list[tuple[float, float]]]  # each column's extents seen so far
_Style = tuple[float | None, bool]  # font size and weight


@dataclass(slots=True)
class _Line:
    page: int
    cells: dict[str, list[Word]]  # the words in each column the spec names
    first: str  # the text in the leftmost printed column
    text: str  # the whole printed line
    words: list[Word]  # every word on the line
    edges: dict[str, tuple[float, float]] = field(default_factory=dict)  # without rules


@dataclass(slots=True)
class _Opening:
    """How a page after the table's first could continue it: the lines it would add, whether it
    opens with the header printed again, and the lines that stand above them."""

    lines: list[_Line]
    header: bool
    above: list[tuple[str, str]]  # (first text, whole text) of each line above the table
    edges: _Edges = field(default_factory=dict)  # the repeated header's column extents


@dataclass(slots=True)
class _Cut:
    """The lines `_cut` keeps of a page, and what ended them before the page's end."""

    lines: list[_Line]
    stopped: bool = False  # a `stop:` row
    misfit: _Line | None = None  # a line that does not fit the columns


def _on(pages: list[int]) -> str:
    return f"page {pages[0]}" if len(pages) == 1 else f"pages {', '.join(map(str, pages))}"


def _range(first: int, last: int) -> str:
    return str(first) if first == last else f"{first}-{last}"


def _top(view: View, box: Box) -> float:
    return view.upright(box)[1]


def _listed(found: list[tuple[str, int]]) -> str:
    """'text' on page n, for each text, with every page it is on."""
    pages: dict[str, list[int]] = {}
    for text, page in found:
        if page not in pages.setdefault(text, []):
            pages[text].append(page)
    return ", ".join(f"{t!r} on {_on(ps)}" for t, ps in pages.items())


def _style(view: View, words: list[Word]) -> _Style:
    """The face a run of words is set in: the largest size, and whether all of it is bold."""
    lines = [ln for w in words if (ln := view.line_at(w.start)) is not None]
    sizes = [ln.size for ln in lines if ln.size]
    return (round(max(sizes), 1) if sizes else None), bool(lines) and all(ln.bold for ln in lines)


def _face(style: _Style) -> str:
    size, bold = style
    return ("bold" if bold else "regular") + (f", {size:g} pt" if size else "")


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


def _starts(first: str, labels: tuple[str, ...]) -> bool:
    """Whether `first` begins with one of `labels`, on a word boundary."""
    n = normalize_label(first)
    for label in labels:
        s = normalize_label(label)
        if n.startswith(s) and (len(n) == len(s) or not n[len(s)].isalnum()):
            return True
    return False


def _rows(view: View, groups: list[list[_Line]], keys: list[str]) -> tuple[Row, ...]:
    return tuple(
        Row(
            {
                k: view.place(w for line in group for w in line.cells.get(k, ()))
                for k in keys
                if any(k in line.cells for line in group)
            },
            " ".join(clean(line.text) for line in group),
            group[0].page,
        )
        for group in groups
    )


class _Reader:
    """One kind of table, found on its first page: its lines there, and how another page could
    continue it."""

    method: str
    page: int  # the page the header is printed on
    header: Span
    header_words: list[Word]
    header_text: str  # normalized, to recognise the header printed again

    def __init__(self, view: View, loc: Records) -> None:
        self.view, self.loc = view, loc

    def lines(self, drop: bool) -> list[_Line]:
        """The lines under the header on its page; `drop` leaves the possible running heads
        and feet out."""
        raise NotImplementedError

    def open(self, page: int) -> _Opening | None:
        """How `page` could continue the table, or None when it neither prints the header again
        nor has rows on the same column edges."""
        raise NotImplementedError

    def fit(self, line: _Line) -> bool:  # noqa: ARG002 - a ruled row fits its grid
        """Whether `line` fits the table's columns; a line that fits widens what fits next."""
        return True

    def extend(self, edges: _Edges) -> None:
        """Take the column extents of the header printed again on a page the table reaches."""

    def group(self, lines: list[_Line]) -> tuple[list[list[_Line]], str]:
        """The lines as records, or why a line cannot be given to one."""
        return [[line] for line in lines], ""

    def left_out(self, page: int) -> list[str]:  # noqa: ARG002 - a cell is never furniture
        """The text left out of the table on `page` as running heads and feet."""
        return []


def _cut(reader: _Reader, lines: list[_Line], skipped: list, again: list[int]) -> _Cut:
    """`lines` up to a `stop:` row or a line that does not fit the columns, without the rows
    `skip:` names (added to `skipped`) and the header printed again (its page added to
    `again`)."""
    loc = reader.loc
    out: list[_Line] = []
    for line in lines:
        if _starts(line.first, loc.stop):
            return _Cut(out, stopped=True)
        if _starts(line.first, loc.skip):
            skipped.append((clean(line.text), line.page))
            continue
        if normalize_label(line.text) == reader.header_text:
            again.append(line.page)
            continue
        if not reader.fit(line):
            return _Cut(out, misfit=line)
        out.append(line)
    return _Cut(out)


def _follow(view: View, loc: Records, reader: _Reader) -> Rows:
    """The rows of the table `reader` found, on its page and, in the form `continues:`
    declares, on each following page that continues it."""
    keys = [k for k, _ in loc.header]
    form = loc.continues
    first = reader.page
    later = [n for n in view.numbers if n > first]

    def continuing(n: int) -> _Opening | None:
        o = reader.open(n)
        return o if o is not None and (form == "rows" or o.header) else None

    skipped: list[tuple[str, int]] = []
    again: list[int] = []
    flows = False
    if form:
        cut = _cut(reader, reader.lines(True), skipped, again)
        flows = (
            not cut.stopped
            and cut.misfit is None
            and first + 1 in later
            and continuing(first + 1) is not None
        )
    if not flows:
        skipped, again = [], []
        cut = _cut(reader, reader.lines(False), skipped, again)
    lines = list(cut.lines)
    pages = [first]
    incomplete = ""
    while flows and not cut.stopped and cut.misfit is None and pages[-1] + 1 in later:
        n = pages[-1] + 1
        o = continuing(n)
        if o is None:
            break
        title = next((t for f, t in o.above if not _starts(f, loc.skip)), None)
        if title is not None:
            opens = "prints the header again" if o.header else "opens with rows on its column edges"
            incomplete = (
                f"page {n} {opens} under the line {clean(title)!r}, which is neither a running "
                "head nor a row `skip:` names; if it is a title over the continued table, leave "
                f"it out with `skip:`; if the table ends on page {pages[-1]}, keep the field to "
                f"its pages with `pages: {_range(first, pages[-1])}`"
            )
            break
        skipped += [(clean(t), n) for _, t in o.above]
        if o.header:
            again.append(n)
        reader.extend(o.edges)
        cut = _cut(reader, o.lines, skipped, again)
        lines += cut.lines
        pages.append(n)
    last = pages[-1]

    if not incomplete and lines:
        head, body = _style(view, reader.header_words), _style(view, lines[0].words)
        alike = next((ln for ln in lines[1:] if _style(view, ln.words) == head), None)
        if head != body and alike is not None:
            incomplete = (
                f"the line {clean(alike.text)!r} on page {alike.page} is set like the header "
                f"({_face(head)}), not like the rows ({_face(body)}), so it may be another "
                "table's header; end the table before it with `stop:`, or keep the field to the "
                "table's pages with `pages:`"
            )

    def reprinted(n: int) -> bool:
        o = reader.open(n)
        return o is not None and (o.header or (form != "header" and not o.above))

    elsewhere = [] if incomplete else [n for n in later if n > last and reprinted(n)]
    if elsewhere and not form:
        incomplete = (
            f"{_AGAIN} {_on(elsewhere)}; if the table runs over pages, declare how with "
            "`continues: header` (each page opens with the header) or `continues: rows` (each "
            f"page opens with rows on the same column edges); if it does not, keep the field to "
            f"page {first} with `pages: {first}`"
        )
    elif elsewhere:
        if cut.stopped:
            how = "at a `stop:` row"
        elif cut.misfit is not None:
            how = f"at the line {clean(cut.misfit.text)!r}, which does not fit its columns"
        elif form == "header":
            how = f"because page {last + 1} does not open with its header"
        else:
            how = f"because page {last + 1} does not continue it"
        incomplete = (
            f"the table ends on page {last} {how}, but {_AGAIN} {_on(elsewhere)}; keep the field "
            f"to the table's pages with `pages: {_range(first, last)}`"
        )

    notes: list[str] = []
    if skipped:
        notes.append(f"left out by `skip:`: {_listed(skipped)}")
    if again:
        notes.append(f"left out the header printed again on {_on(sorted(set(again)))}")
    left: list[tuple[str, int]] = []
    if len(pages) > 1:
        left = [(clean(text), n) for n in pages for text in reader.left_out(n)]
    if left:
        notes.append(f"left out as running heads and feet: {_listed(left)}")
    if loc.filled and not isinstance(reader, _Layout):
        notes.append(
            "`filled:` applies only to tables without rules, and this table is ruled: each of "
            "its rows is a record"
        )
    if cut.misfit is not None:
        line = cut.misfit
        notes.append(
            f"the table ends at the line {clean(line.text)!r} on page {line.page}, which does "
            "not fit its columns"
        )
    if (
        form
        and not cut.stopped
        and cut.misfit is None
        and view.pages is not None
        and last == view.pages[1]
        and view.layer.pages
        and last < view.layer.pages[-1].number
    ):
        notes.append(f"the table may go on after page {last}, outside the field's pages")
    groups, ambiguous = reader.group(lines)
    return Rows(
        reader.method,
        reader.header,
        _rows(view, groups, keys),
        tuple(pages),
        tuple(notes),
        incomplete,
        ambiguous,
    )


# --- records in tables --------------------------------------------------------------------------


def _header_row(
    view: View, table: Table, wanted: list[tuple[str, str]]
) -> tuple[int, dict[str, int], list[TableCell]] | None:
    """The first row of `table` that holds every wanted header: its number, each key's column,
    and its printed cells left to right."""
    cells = view.by_table[table.id]
    for r in range(table.rows):
        row = {normalize_label(view.text(c.start, c.end)): c for c in cells if c.row == r}
        if all(h in row for _, h in wanted):
            printed = sorted((c for c in row.values() if c.end > c.start), key=lambda c: c.col)
            return r, {k: row[h].col for k, h in wanted}, printed
    return None


def _printed_row(view: View, table: Table, r: int) -> list[TableCell]:
    """The cells that start in row `r` and print something, left to right."""
    cells = view.by_table[table.id]
    return sorted((c for c in cells if c.row == r and c.end > c.start), key=lambda c: c.col)


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
        printed = _printed_row(view, table, r)
        texts = [view.text(c.start, c.end) for c in printed]
        every = [w for c in printed for w in view.words_between(c.start, c.end)]
        lines.append(_Line(table.page, words, texts[0] if texts else "", " ".join(texts), every))
    return lines


def _edges(view: View, table: Table) -> list[float]:
    cells = [c for c in view.by_table[table.id] if c.col_span == 1]
    lefts = {c.col: view.upright(c.box)[0] for c in sorted(cells, key=lambda c: -c.row)}
    return [lefts.get(col, float("nan")) for col in range(table.cols)] + [
        view.upright(table.box)[2]
    ]


class _Ruled(_Reader):
    method = "records"

    def __init__(
        self, view: View, loc: Records, table: Table, found: tuple[int, dict, list]
    ) -> None:
        super().__init__(view, loc)
        self.table = table
        row, self.cols, printed = found
        self.start = row + 1
        self.page = table.page
        self.header = Span(min(c.start for c in printed), max(c.end for c in printed))
        self.header_words = [w for c in printed for w in view.words_between(c.start, c.end)]
        self.header_text = normalize_label(" ".join(view.text(c.start, c.end) for c in printed))
        self.wanted = [(k, normalize_label(h)) for k, h in loc.header]

    def lines(self, drop: bool) -> list[_Line]:  # noqa: ARG002 - nothing in a cell is furniture
        return _table_lines(self.view, self.table, self.start, self.cols)

    def open(self, page: int) -> _Opening | None:
        """The first table on `page` that holds the header or has the same column edges; the
        lines above it are those printed above the table that are not running heads, and its
        own rows above the header or its title rows."""
        view = self.view
        for t in (t for t in view.tables if t.page == page):
            if found := _header_row(view, t, self.wanted):
                head, start, cols, header = found[0], found[0] + 1, found[1], True
            else:
                a, b = _edges(view, self.table), _edges(view, t)
                if len(a) != len(b) or not all(
                    abs(x - y) <= _ALIGNED for x, y in zip(a, b, strict=True)
                ):
                    continue
                titles = {c.row for c in view.by_table[t.id] if c.role == "title"}
                head, start, cols, header = len(titles), len(titles), self.cols, False
            top = _top(view, t.box)
            above = [
                (text, text)
                for ln in view.lines_on(page)
                if view.upright(ln.box)[3] <= top + 1 and ln.start not in view.index.furniture
                for text in [view.text(ln.start, ln.end)]
            ]
            for r in range(head):
                if texts := [view.text(c.start, c.end) for c in _printed_row(view, t, r)]:
                    above.append((texts[0], " ".join(texts)))
            return _Opening(_table_lines(view, t, start, cols), header, above)
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
    extents: dict[str, tuple[float, float]]  # where each header starts and ends
    top: float  # rows start below this: the bottom of the header row

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
    return _Columns(order, bounds, extents, max(b[3] for _, b in row))


def _layout_line(view: View, row: _Printed, cols: _Columns, page: int) -> _Line:
    printed: dict[str, _Printed] = {}
    for w, b in row:
        printed.setdefault(cols.of(b[0], b[2]), []).append((w, b))
    # The first text is the leftmost column's, printed or left out of the spec: a stop label
    # such as "Subtotal" may stand in a column the spec does not name.
    leftmost = min(printed.values(), key=lambda ws: ws[0][1][0])
    first = " ".join(view.text(w.start, w.end) for w, _ in leftmost)
    text = " ".join(view.text(w.start, w.end) for w, _ in row)
    cells = {k: [w for w, _ in ws] for k, ws in printed.items() if not k.startswith("\0")}
    edges = {k: (ws[0][1][0], ws[-1][1][2]) for k, ws in printed.items()}
    return _Line(page, cells, first, text, [w for w, _ in row], edges)


def _layout_lines(view: View, rows: list[_Printed], cols: _Columns, page: int) -> list[_Line]:
    """Every printed line whose middle is below `cols.top`, to the end of the page: tight rows
    can start above the header's bottom edge."""
    return [
        _layout_line(view, r, cols, page) for r in rows if r[0][1][1] + r[0][1][3] > 2 * cols.top
    ]


def _fits(line: _Line, edges: _Edges) -> bool:
    """Whether each column `line` prints in starts, ends or is centred where that column's
    header, or a cell already read in it, starts, ends or is centred."""
    for key, (x0, x1) in line.edges.items():
        if not any(
            abs(x0 - a) <= _ALIGNED
            or abs(x1 - b) <= _ALIGNED
            or abs(x0 + x1 - a - b) <= 2 * _ALIGNED
            for a, b in edges.get(key, ())
        ):
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
        self,
        view: View,
        loc: Records,
        heads: dict[int, list[int]],
        page: int,
        row: _Printed,
        cols: _Columns,
    ) -> None:
        super().__init__(view, loc)
        self.heads, self.page, self.cols = heads, page, cols
        self.header = Span(min(w.start for w, _ in row), max(w.end for w, _ in row))
        self.header_words = [w for w, _ in row]
        self.header_text = normalize_label(" ".join(view.text(w.start, w.end) for w, _ in row))
        self.top = min(b[1] for _, b in row)
        self.edges: _Edges = {k: [e] for k, e in cols.extents.items()}

    def lines(self, drop: bool) -> list[_Line]:
        rows = _page_rows(self.view, self.page, self.loc, self.cols if drop else None)
        return _layout_lines(self.view, rows, self.cols, self.page)

    def fit(self, line: _Line) -> bool:
        if not _fits(line, self.edges):
            return False
        for key, extent in line.edges.items():
            self.edges[key].append(extent)
        return True

    def extend(self, edges: _Edges) -> None:
        for key, extents in edges.items():
            self.edges.setdefault(key, []).extend(extents)

    def left_out(self, page: int) -> list[str]:
        _, left = _split(self.view, page, self.loc, self.cols)
        view = self.view
        return [
            " ".join(view.text(w.start, w.end) for w, _ in r)
            for r in left
            if page != self.page or r[0][1][1] >= self.top
        ]

    def open(self, page: int) -> _Opening | None:
        """The first printed row of `page`, after running heads, that holds every header, or
        fills at least two columns on the edges the table's first page sets; the rows above it
        are the lines above the table."""
        view, loc = self.view, self.loc
        rows = _page_rows(view, page, loc, self.cols)
        starts = set(self.heads.get(page, []))
        for i, r in enumerate(rows):
            above = [
                (x.first, x.text)
                for x in (_layout_line(view, a, self.cols, page) for a in rows[:i])
            ]
            if any(w.start in starts for w, _ in r) and (cols := _columns(view, r, loc)):
                edges = {k: [e] for k, e in cols.extents.items()}
                return _Opening(_layout_lines(view, rows, cols, page), True, above, edges)
            line = _layout_line(view, r, self.cols, page)
            if len(line.cells) >= 2 and _fits(line, self.edges):
                cols = replace(self.cols, top=r[0][1][1])
                return _Opening(_layout_lines(view, rows, cols, page), False, above)
        return None

    def group(self, lines: list[_Line]) -> tuple[list[list[_Line]], str]:
        """Printed lines as records. Without `filled`, every line must fill every column. With
        it, a line that fills the named columns starts a record (`first`) or ends one (`last`),
        and every other line joins that record."""
        loc = self.loc
        keys = [k for k, _ in loc.header]
        marks = set(loc.filled)
        apart = "if the line is not part of the table, end the table before it with `stop:` or "
        apart += "leave it out with `skip:`"
        if not marks:
            for line in lines:
                if set(line.cells) != set(keys):
                    lacking = [k for k in keys if k not in line.cells] or keys
                    return [], (
                        f"{_partial(line, keys)}, so it may continue a record or be one of its "
                        "own; say which columns every record fills on its first line with "
                        f"`filled: {{first: [{', '.join(lacking)}]}}` (or on its last line with "
                        f"`filled: {{last: [...]}}`); {apart}"
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
                        f"{', '.join(loc.filled)}, so it belongs to no record; if every record "
                        "fills other columns on its first line, name those in `filled:`, or "
                        f"declare `filled: {{last: [...]}}` if it fills them on its last; {apart}"
                    )
            else:
                pending.append(line)
                if marked:
                    groups.append(pending)
                    pending = []
        if pending:
            return [], (
                f"{_partial(pending[0], keys)} and comes after the last line that fills "
                f"{', '.join(loc.filled)}, so it belongs to no record; if every record fills "
                "other columns on its last line, name those in `filled:`, or declare "
                f"`filled: {{first: [...]}}` if it fills them on its first; {apart}"
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
    each column spans its header's width, and rows run while they fit the columns, until a
    `stop:` row or the end of the page."""
    heads: dict[int, list[int]] = {}
    for span in view.find_label(loc.header[0][1]):
        if not view.cell_at(span.start):
            heads.setdefault(view.page_of(span.start), []).append(span.start)
    for page, starts in heads.items():
        found = _header(view, loc, _page_rows(view, page, loc, None), starts)
        if found is not None:
            return _Layout(view, loc, heads, page, *found)
    return None
