"""What the author of a spec needs to know about a document before writing one.

`inspect` answers: is each page's text trustworthy, which tables were found and what their rows
say, which lines look like headings, and where a phrase is printed. It shows the layer exactly as
the locators see it, so a label that `inspect` cannot find cannot be extracted either.
"""

from dataclasses import dataclass

from janus_pdf._index import index_of, normalize_label, rank
from janus_pdf.document import Box, Layer
from janus_pdf.values import clean


@dataclass(frozen=True, slots=True)
class PageSummary:
    """One page: its size in points as displayed, how its text was obtained, how many words it
    has, and its tables."""

    number: int
    width: float
    height: float
    kind: str  # "text", "ocr" or "broken_encoding"
    words: int
    tables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TableSummary:
    """One table: its ID for `cell` locators, its size, and the text of its first rows."""

    id: str
    page: int
    rows: int
    cols: int
    preview: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class Hit:
    """One line or cell a searched phrase is printed in."""

    page: int
    text: str  # the whole line or cell
    box: Box
    starts_line: bool  # whether a `label` locator would accept it
    cell: str | None  # "p5t0 r3 c0" when it is in a table


@dataclass(frozen=True, slots=True)
class Heading:
    """A line the `section` locator treats as a heading."""

    page: int
    size: float
    bold: bool
    text: str
    box: Box


@dataclass(frozen=True, slots=True)
class Inspection:
    """A layer as the locators see it: pages, tables, headings, and where a phrase is."""

    document: str
    layer: str
    engine: str
    pages: tuple[PageSummary, ...]
    tables: tuple[TableSummary, ...]
    headings: tuple[Heading, ...]
    hits: tuple[Hit, ...]


def inspect(
    layer: Layer, page: int | None = None, find: str | None = None, rows: int = 4
) -> Inspection:
    """Summarise `layer`, or one `page` of it, previewing `rows` rows of each table.

    With `find`, also list every line and cell that contains the phrase, and whether a `label`
    locator would accept it there.
    """
    ix = index_of(layer)

    def on(number: int) -> bool:
        return page is None or number == page

    pages = tuple(
        PageSummary(
            p.number,
            p.width,
            p.height,
            p.triage.kind if p.triage else "text",
            sum(1 for w in layer.words if w.box.page == p.number),
            tuple(t.id for t in layer.tables if t.page == p.number),
        )
        for p in layer.pages
        if on(p.number)
    )
    tables = []
    for t in layer.tables:
        if not on(t.page):
            continue
        cells = ix.by_table[t.id]
        preview = tuple(
            tuple(
                clean(ix.text(c.start, c.end))
                for c in sorted((c for c in cells if c.row == r), key=lambda c: c.col)
            )
            for r in range(min(rows, t.rows))
        )
        tables.append(TableSummary(t.id, t.page, t.rows, t.cols, preview))
    headings = tuple(
        Heading(h.box.page, *rank(h), clean(ix.text(h.start, h.end)), h.box)
        for h in ix.headings
        if on(h.box.page)
    )
    hits = []
    if find:
        needle = normalize_label(find)
        units = [(ln.start, ln.end, ln.box, None) for ln in layer.lines] + [
            (c.start, c.end, c.box, f"{c.table_id} r{c.row} c{c.col}") for c in layer.cells
        ]
        for start, end, box, cell in units:
            printed = ix.text(start, end)
            if not on(box.page) or needle not in normalize_label(printed):
                continue
            if cell is None and ix.cell_at(start):
                continue  # reported as the cell
            starts = normalize_label(printed).startswith(needle)
            hits.append(Hit(box.page, clean(printed), box, starts, cell))
    return Inspection(
        layer.document_hash,
        layer.id,
        layer.recipe.engine,
        pages,
        tuple(tables),
        headings,
        tuple(hits),
    )
