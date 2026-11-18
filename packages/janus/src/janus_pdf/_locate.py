"""The five locators. Each finds every place a field's value is printed, or says why it found
none. Reading what they find, and deciding what that means, is `extract`'s job.

A place is the exact words of one printed value, as spans of the layer text in reading order:
one span when the words follow one another, several when other words are printed between them
(a region beside another column, a description wrapped under a quantity). Locators read the layer
through a `View`, so a field's pages apply to all of them alike.
"""

import re
from dataclasses import dataclass, field
from itertools import pairwise
from statistics import median

from janus_pdf._index import View, normalize_label, rank
from janus_pdf.document import Line, Span, Table, TableCell, Word
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


@dataclass(frozen=True, slots=True)
class Row:
    """One record's cells by key, the row's first printed text, and its page."""

    cells: dict[str, Place]
    first: str
    page: int


@dataclass(frozen=True, slots=True)
class Rows:
    """A records locator's result: the header it matched and the rows under it.

    `incomplete` says why the rows may not be all of them (a table that runs off its page with
    no certain continuation); `ambiguous` says which printed line could belong to two records.
    Either one means the rows are not a value.
    """

    method: str  # "records" for a table, "records:layout" for printed rows without rules
    header: Span
    rows: tuple[Row, ...]
    pages: tuple[int, ...] = ()
    skipped: tuple[str, ...] = ()  # carried-forward and continued lines, left out
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
    return _table_records(view, loc) or _line_records(view, loc)


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
    wanted = {normalize_label(h) for h in loc.heading}
    headings = view.index.headings  # a section ends at the next heading, on any page
    found = Found("section")
    parents: list[str | None] = []
    for i, h in enumerate(headings):
        if normalize_label(view.text(h.start, h.end)) not in wanted or not view.on(h.box.page):
            continue
        parent = _parent(view, headings, i)
        if loc.under is not None and normalize_label(parent or "") != normalize_label(loc.under):
            continue
        nxt = next((n for n in headings[i + 1 :] if rank(n) >= rank(h)), None)
        if span := _strip(view, h.end, nxt.start if nxt else len(view.layer.text)):
            found.places.append((span,))
            parents.append(parent)
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
        if not headings:
            found.reason += "; the layer has no font sizes, so it has no headings"
    return found


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
# A table's rows become printed lines (`_Line`): the words in each column and the line's first
# text. Both kinds of table then go through the same steps: carried-forward and continued lines
# are left out, a stop label ends the rows, and a table that runs to the foot of its page is
# followed onto the next page only when the continuation is certain.

_CARRIED = re.compile(
    r"\(?(?:continued|cont(?:'|\u2019)?d\.?|(?:balance )?(?:carried|brought) (?:forward|over)"
    r"|c/f|b/f)\)?[:.]?"
)
_CONTINUED = re.compile(
    r"\b(?:continued|cont(?:'|\u2019)?d|(?:carried|brought) (?:forward|over))\b"
)
_ALIGNED = 1.5  # points: column edges this close are the same column


@dataclass(slots=True)
class _Line:
    page: int
    cells: dict[str, list[Word]]
    first: str  # the text in the leftmost column
    top: float


def _free(view: View, line: Line) -> bool:
    """A line that is not part of any table's content: page furniture, or a "continued" line."""
    if line.start in view.index.furniture:
        return True
    return bool(_CONTINUED.search(normalize_label(view.text(line.start, line.end))))


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


def _next_page(view: View, page: int, carried: bool) -> tuple[int | None, str]:
    """The page rows that run to the foot of `page` go on to, or None when they end there, with
    the reason they may not end there. They end on the document's last page, and on the last of
    the field's pages unless a carried-forward line says they go on."""
    last = view.layer.pages[-1].number if view.layer.pages else page
    if page >= last:
        return None, ""
    if not view.on(page + 1):
        why = f"its last line carries it forward to page {page + 1}, outside the field's pages"
        return None, why if carried else ""
    return page + 1, ""


_SETTLE = "; if the rows end on page {page}, say so with `pages:` or a `stop:` label"


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
        first = view.text(printed[0].start, printed[0].end) if printed else ""
        top = min((c.box.y0 for c in row), default=0.0)
        lines.append(_Line(table.page, words, first, top))
    return lines


def _runs_to_foot(view: View, page: int, bottom: float) -> bool:
    """Whether nothing but page furniture and continued lines is printed below `bottom`."""
    return all(_free(view, ln) for ln in view.lines_on(page) if ln.box.y0 >= bottom - 1)


def _edges(view: View, table: Table) -> list[float]:
    cells = [c for c in view.by_table[table.id] if c.col_span == 1]
    lefts = {c.col: c.box.x0 for c in sorted(cells, key=lambda c: -c.row)}
    return [lefts.get(col, float("nan")) for col in range(table.cols)] + [table.box.x1]


def _table_continues(
    view: View, prev: Table, cols: dict[str, int], wanted: list[tuple[str, str]], page: int
) -> tuple[Table, int, dict[str, int]] | str:
    """The table that certainly continues `prev` on `page`, the row its records start at and its
    columns; or why the continuation is not certain."""
    nxt = next((t for t in view.tables if t.page == page), None)
    if nxt is None:
        return f"page {page} has no table to continue it"
    above = [
        ln for ln in view.lines_on(page) if ln.box.y1 <= nxt.box.y0 + 1 and not _free(view, ln)
    ]
    if above:
        printed = clean(view.text(above[0].start, above[0].end))
        return f"page {page} prints {printed!r} before its first table"
    if found := _header_row(view, nxt, wanted):
        return nxt, found[0] + 1, found[1]
    a, b = _edges(view, prev), _edges(view, nxt)
    if len(a) == len(b) and all(abs(x - y) <= _ALIGNED for x, y in zip(a, b, strict=True)):
        titles = {c.row for c in view.by_table[nxt.id] if c.role == "title"}
        return nxt, len(titles), cols
    return f"the first table on page {page} neither repeats the header nor has the same columns"


def _table_records(view: View, loc: Records) -> Rows | None:
    wanted = [(k, normalize_label(h)) for k, h in loc.header]
    keys = [k for k, _ in loc.header]
    for table in view.tables:
        found = _header_row(view, table, wanted)
        if found is None:
            continue
        r, cols, header = found
        skipped: list[str] = []
        lines, stopped, carried = _cut(_table_lines(view, table, r + 1, cols), loc, skipped)
        pages, incomplete, current = [table.page], "", table
        while not stopped and _runs_to_foot(view, current.page, current.box.y1):
            page, why = _next_page(view, current.page, carried)
            if page is None:
                incomplete = why and f"the table runs to the foot of page {current.page}; {why}"
                break
            cont = _table_continues(view, current, cols, wanted, page)
            if isinstance(cont, str):
                incomplete = f"the table runs to the foot of page {current.page}, and {cont}"
                incomplete += _SETTLE.format(page=current.page)
                break
            current, start, cols = cont
            more, stopped, carried = _cut(_table_lines(view, current, start, cols), loc, skipped)
            lines += more
            pages.append(page)
        groups = [[line] for line in lines]  # a table's rows are the table's rows
        return Rows(
            "records", header, _rows(view, groups, keys), tuple(pages), tuple(skipped), incomplete
        )
    return None


# --- records printed without a table ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Columns:
    order: list[str]  # keys left to right; "\0n" for a printed column the spec leaves out
    bounds: dict[str, tuple[float, float]]
    top: float  # the bottom of the header row

    def of(self, w: Word) -> str:
        """The column `w` is printed in; a "\0" key is a column the spec leaves out."""
        mid = (w.box.x0 + w.box.x1) / 2
        return next(k for k in self.order if self.bounds[k][0] <= mid < self.bounds[k][1])


def _visual_rows(words: list[Word]) -> list[list[Word]]:
    rows: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.box.y0, w.box.x0)):
        mid = (w.box.y0 + w.box.y1) / 2
        if rows and rows[-1][0].box.y0 <= mid <= rows[-1][0].box.y1:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w.box.x0) for r in rows]


def _page_rows(view: View, page: int, loc: Records) -> list[list[Word]]:
    """The printed rows of `page`, without page furniture. A header repeated at the top of every
    page looks like a running head; it is kept."""
    headers = {t for _, h in loc.header for t in normalize_label(h).split()}
    furniture = [
        ln
        for ln in view.lines_on(page)
        if ln.start in view.index.furniture
        and not set(normalize_label(view.text(ln.start, ln.end)).split()) <= headers
    ]
    words = [
        w
        for w in view.words
        if w.box.page == page and not any(ln.start <= w.start < ln.end for ln in furniture)
    ]
    return _visual_rows(words)


def _columns(view: View, row: list[Word], loc: Records) -> _Columns | None:
    """The columns a printed header row sets, when it holds every header of `loc`."""
    texts = [normalize_label(view.text(w.start, w.end)) for w in row]
    extents: dict[str, tuple[float, float]] = {}
    claimed: set[int] = set()
    for key, header in loc.header:
        parts = normalize_label(header).split()
        for i in range(len(texts) - len(parts) + 1):
            if texts[i : i + len(parts)] == parts and not claimed & set(range(i, i + len(parts))):
                ws = row[i : i + len(parts)]
                extents[key] = (ws[0].box.x0, ws[-1].box.x1)
                claimed.update(range(i, i + len(parts)))
                break
    if len(extents) != len(loc.header):
        return None
    # A printed column the spec leaves out still bounds its neighbours; its words are dropped.
    run: list[Word] = []
    for i, w in enumerate([*row, None]):
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
    return _Columns(order, bounds, max(w.box.y1 for w in row))


def _layout_lines(
    view: View, rows: list[list[Word]], cols: _Columns, page: int
) -> tuple[list[_Line], bool]:
    """The printed lines under a header row, and whether they run to the foot of the page
    rather than ending at a gap."""
    below = [r for r in rows if r[0].box.y0 >= cols.top - 0.5]
    gap = 2.2 * median([r[0].box.y1 - r[0].box.y0 for r in below[:5]] or [10.0])
    out, last = [], cols.top
    for r in below:
        if r[0].box.y0 - last > gap:
            return out, False
        printed: dict[str, list[Word]] = {}
        for w in r:
            printed.setdefault(cols.of(w), []).append(w)
        # The first text is the leftmost column's, printed or left out of the spec: a stop label
        # such as "Subtotal" may stand in a column the spec does not name.
        leftmost = min(printed.values(), key=lambda ws: ws[0].box.x0)
        first = " ".join(view.text(w.start, w.end) for w in leftmost)
        cells = {k: ws for k, ws in printed.items() if not k.startswith("\0")}
        out.append(_Line(page, cells, first, min(w.box.y0 for w in r)))
        last = max(w.box.y1 for w in r)
    return out, True


def _aligned(line: _Line, before: list[_Line]) -> bool:
    """Whether every column `line` fills starts or ends where the same column does in the lines
    above, in at least two columns."""
    if len(line.cells) < 2:
        return False
    for key, ws in line.cells.items():
        x0, x1 = ws[0].box.x0, ws[-1].box.x1
        edges = [
            (b.cells[key][0].box.x0, b.cells[key][-1].box.x1) for b in before if key in b.cells
        ]
        if not any(abs(x0 - a) <= _ALIGNED or abs(x1 - b) <= _ALIGNED for a, b in edges):
            return False
    return True


def _group(lines: list[_Line], loc: Records) -> tuple[list[list[_Line]], str]:
    """Printed lines as records. A line that fills only some of the columns its record's first
    line fills is a wrapped line of that record when the page settles it: it is set closer to
    the line above than records are to one another (at most three quarters of the closest record
    spacing). With `filled`, a line with nothing in that column continues the record above.
    When neither settles it, the second return says which line could go either way."""
    starts = [
        b.top - a.top
        for a, b in pairwise(lines)
        if a.page == b.page and not set(b.cells) < set(a.cells)
    ]
    pitch = min(starts) if starts else None
    groups: list[list[_Line]] = []
    for prev, line in zip([None, *lines], lines, strict=False):
        if prev is None or not groups:
            groups.append([line])
            continue
        record = groups[-1][0]
        if loc.filled is not None:
            wrapped = loc.filled not in line.cells
        elif not set(line.cells) < set(record.cells):
            wrapped = False
        elif line.page == prev.page and pitch is not None and line.top - prev.top <= 0.75 * pitch:
            wrapped = True
        else:
            spacing = (
                "it starts a new page"
                if line.page != prev.page
                else f"it is {line.top - prev.top:.1f} pt below the line above"
                + (f" and records are {pitch:.1f} pt apart" if pitch is not None else "")
            )
            filled = ", ".join(sorted(line.cells))
            return groups, (
                f"the line {clean(line.first)!r} on page {line.page} prints only {filled}; "
                f"{spacing}, so it may continue the record {clean(record.first)!r} or be a "
                "record of its own. Name a column every record fills with `filled:` to settle it"
            )
        if wrapped:
            groups[-1].append(line)
        else:
            groups.append([line])
    return groups, ""


def _line_records(view: View, loc: Records) -> Rows | None:
    """Records laid out without rules: the header is a printed row holding every column header,
    each column spans its header's width, and rows run until a gap, a stop label or the foot of
    the page, and on to the next page when it certainly continues them."""
    _, first_header = loc.header[0]
    keys = [k for k, _ in loc.header]
    for span in view.find_label(first_header):
        if view.cell_at(span.start):
            continue
        page = view.page_of(span.start)
        start_word = next(view.words_between(span.start, span.end))
        rows = _page_rows(view, page, loc)
        header_row = next((r for r in rows if start_word in r), None)
        cols = _columns(view, header_row, loc) if header_row else None
        if header_row is None or cols is None:
            continue
        skipped: list[str] = []
        found, at_foot = _layout_lines(view, rows, cols, page)
        lines, stopped, carried = _cut(found, loc, skipped)
        pages, incomplete = [page], ""
        while not stopped and at_foot:
            nxt, why = _next_page(view, page, carried)
            if nxt is None:
                incomplete = why and f"the rows run to the foot of page {page}; {why}"
                break
            rows = _page_rows(view, nxt, loc)
            if not rows:
                break
            again = _columns(view, rows[0], loc)
            if again is not None:
                cols = again
            else:
                cols = _Columns(cols.order, cols.bounds, rows[0][0].box.y0 - 0.5)
                probe, _ = _layout_lines(view, rows, cols, nxt)
                if not probe or not _aligned(probe[0], lines):
                    incomplete = (
                        f"the rows run to the foot of page {page}, and page {nxt} neither repeats "
                        "the header nor starts with a row under the same columns"
                    ) + _SETTLE.format(page=page)
                    break
            page = nxt
            found, at_foot = _layout_lines(view, rows, cols, page)
            more, stopped, carried = _cut(found, loc, skipped)
            lines += more
            pages.append(page)
        groups, ambiguous = _group(lines, loc)
        header = Span(min(w.start for w in header_row), max(w.end for w in header_row))
        return Rows(
            "records:layout",
            header,
            _rows(view, groups, keys),
            tuple(pages),
            tuple(skipped),
            incomplete,
            ambiguous,
        )
    return None
