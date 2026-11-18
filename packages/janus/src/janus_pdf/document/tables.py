"""Table grids from the text layer.

PyMuPDF's `find_tables` gates borderless tables with its Layout model, which Janus does not use
until its source is published. Without it, only fully
ruled tables are found. Many printed tables have only three rules, so this module also finds a
table from its "Table N" caption and the full-width rules below it, then builds the grid from the
words themselves:

- rows are printed lines;
- columns are the x-ranges that most rows leave empty, and each boundary sits in the part of its
  range that the fewest words reach into, so a long row label stays in its column;
- in the body every word belongs to the column under its centre, so no body cell crosses a
  boundary;
- a header phrase that crosses a column gap spans those columns, up to the column where the next
  phrase of its row starts, and a rule printed under a header cell extends it over the empty
  columns it covers ("Site A (n = 120)" over three habitats);
- an empty header cell under a header cell merges into it ("Parameter" over two header rows);
- a leading row whose one cell spans every column is a title, not a header.

Fully ruled tables come from `find_tables`, and `grid_from_ruling` takes their cells from the
rules themselves.

Docling's TableFormer grids go through `grid_from_cells`, so both paths give cell rectangles that
tile the table and receive the text layer's words.
"""

import re
from dataclasses import dataclass
from statistics import median

from janus_pdf.document.layout import Grid, GridCell, PBlock, PWord, Rect, group_rows, union
from janus_pdf.document.model import CellRole

# v2: ruled tables take their cells from the rules, body words never cross a column, title rows.
TABLES_VERSION = "janus.tables.v2"

_CAPTION = re.compile(r"^Table\s+\d+[A-Za-z]?\b")
_RULE_TOLERANCE = 12.0  # points by which a table's rules may differ in extent
_CAPTION_TO_RULE = 40.0
_MAX_HEADER_ROWS = 4


@dataclass(frozen=True, slots=True)
class Rule:
    x0: float
    x1: float
    y: float


def horizontal_rules(segments: list[Rect]) -> list[Rule]:
    """Horizontal strokes and hairline rectangles, with touching segments joined.

    `segments` are stroked lines (as degenerate rectangles) and filled rectangles.
    """
    raw = [
        Rule(r[0], r[2], (r[1] + r[3]) / 2)
        for r in segments
        if r[3] - r[1] < 1.5 and r[2] - r[0] > 2
    ]
    raw.sort(key=lambda r: (round(r.y, 1), r.x0))
    joined: list[Rule] = []
    for r in raw:
        last = joined[-1] if joined else None
        if last and abs(last.y - r.y) < 0.5 and r.x0 <= last.x1 + 1.5:
            joined[-1] = Rule(last.x0, max(last.x1, r.x1), last.y)
        else:
            joined.append(r)
    return joined


def caption_regions(blocks: list[PBlock], rules: list[Rule]) -> list[Rect]:
    """Regions of three-rule tables: from the first rule under a "Table N" caption to the last
    rule of the same width before the next caption."""
    captions = []
    for block in blocks:
        if block.lines and block.lines[0]:
            first = " ".join(w.text for w in block.lines[0][:3])
            if _CAPTION.match(first):
                captions.append(block.lines[0][0].rect[1])
    captions.sort()
    regions: list[Rect] = []
    for i, top in enumerate(captions):
        stop = captions[i + 1] if i + 1 < len(captions) else float("inf")
        below = [r for r in rules if top < r.y < min(stop, top + _CAPTION_TO_RULE)]
        if not below:
            continue
        first = min(below, key=lambda r: r.y)
        same = [
            r
            for r in rules
            if first.y < r.y < stop
            and abs(r.x0 - first.x0) <= _RULE_TOLERANCE
            and abs(r.x1 - first.x1) <= _RULE_TOLERANCE
        ]
        if same:
            bottom = max(r.y for r in same)
            regions.append((first.x0, first.y, first.x1, bottom))
    return regions


def _phrases(row: list[PWord], gap: float) -> list[tuple[float, float, list[PWord]]]:
    out: list[tuple[float, float, list[PWord]]] = []
    for w in row:
        if out and w.rect[0] - out[-1][1] < gap:
            x0, x1, ws = out[-1]
            out[-1] = (x0, max(x1, w.rect[2]), [*ws, w])
        else:
            out.append((w.rect[0], w.rect[2], [w]))
    return out


def _columns(
    rows: list[list[tuple[float, float, list[PWord]]]], lo: float, hi: float
) -> list[float]:
    """Column boundaries: x-ranges that at most a tenth of the rows cover."""
    step = 0.5
    n = max(int((hi - lo) / step) + 1, 1)
    cover = [0] * n
    for phrases in rows:
        hit = [False] * n
        for x0, x1, _ in phrases:
            for k in range(max(int((x0 - lo) / step), 0), min(int((x1 - lo) / step) + 1, n)):
                hit[k] = True
        for k in range(n):
            cover[k] += hit[k]
    threshold = max(1, len(rows) // 10)
    bounds = [lo]
    k = 0
    while k < n:
        if cover[k] <= threshold:
            j = k
            while j < n and cover[j] <= threshold:
                j += 1
            if (j - k) * step >= 3.0 and k > 0 and j < n:
                bounds.append(lo + _clearest(cover[k:j], k) * step)
            k = j
        else:
            k += 1
    bounds.append(hi)
    return bounds


def _title_rows(first_spans: list[tuple[int, int]], ncols: int, nrows: int) -> int:
    """Leading rows whose only cell spans every column, while a header and a body row remain."""
    titles = 0
    while titles < min(len(first_spans), nrows - 2) and first_spans[titles] == (0, ncols - 1):
        titles += 1
    return titles


def _clearest(cover: list[int], offset: int) -> float:
    """The middle of the longest stretch of the gap that the fewest rows cover, so a boundary
    falls between the words of the rows that reach into the gap, not through them."""
    least = min(cover)
    best = (0, 0)
    k = 0
    while k < len(cover):
        if cover[k] == least:
            j = k
            while j < len(cover) and cover[j] == least:
                j += 1
            if j - k > best[1] - best[0]:
                best = (k, j)
            k = j
        else:
            k += 1
    return offset + (best[0] + best[1]) / 2


def grid_from_words(rect: Rect, words: list[PWord], rules: list[Rule]) -> Grid | None:
    """Build a table grid from the words inside `rect`."""
    lines = group_rows(words)
    if len(lines) < 2:
        return None
    height = median(w.rect[3] - w.rect[1] for w in words)
    phrase_rows = [_phrases(line, gap=0.45 * height) for line in lines]
    bounds = _columns(phrase_rows, rect[0], rect[2])
    ncols = len(bounds) - 1
    if ncols < 2:
        return None
    row_tops = [min(w.rect[1] for w in line) for line in lines]
    row_bottoms = [max(w.rect[3] for w in line) for line in lines]
    ybounds = [rect[1]]
    ybounds += [(row_bottoms[i] + row_tops[i + 1]) / 2 for i in range(len(lines) - 1)]
    ybounds.append(max(rect[3], row_bottoms[-1]))

    def col_of(x: float) -> int:
        for c in range(ncols):
            if x < bounds[c + 1]:
                return c
        return ncols - 1

    def header_spans(
        phrases: list[tuple[float, float, list[PWord]]],
    ) -> list[tuple[int, int, list[PWord]]]:
        """A header phrase covers the columns it crosses, up to the column where the next phrase
        of its row starts; phrases that start in one column are one cell."""
        starts = [col_of(x0 + 0.5) for x0, _, _ in phrases]
        spans: list[tuple[int, int, list[PWord]]] = []
        for i, (_, x1, ws) in enumerate(phrases):
            c0, c1 = starts[i], col_of(x1 - 0.5)
            following = starts[i + 1] if i + 1 < len(phrases) else ncols
            if following > c0:
                c1 = min(c1, following - 1)
            if spans and c0 <= spans[-1][1]:
                a, b, prev = spans[-1]
                spans[-1] = (a, max(b, c1), [*prev, *ws])
            else:
                spans.append((c0, c1, list(ws)))
        return spans

    def body_spans(line: list[PWord]) -> list[tuple[int, int, list[PWord]]]:
        """In the body every word belongs to the column under its centre."""
        by_col: dict[int, list[PWord]] = {}
        for w in line:
            by_col.setdefault(col_of(w.cx), []).append(w)
        return [(c, c, ws) for c, ws in sorted(by_col.items())]

    heads = [header_spans(phrases) for phrases in phrase_rows]
    titles = _title_rows(
        [(h[0][0], h[0][1]) if len(h) == 1 else (-1, -1) for h in heads], ncols, len(lines)
    )
    header_end = titles + 1
    while (
        header_end < min(titles + _MAX_HEADER_ROWS, len(lines) - 1)
        and heads[header_end]
        and heads[header_end][0][0] > 0
    ):
        header_end += 1
    spans_by_row = [
        heads[r] if r < header_end else body_spans(line) for r, line in enumerate(lines)
    ]

    # Content extent per column, from body rows only.
    extent: list[tuple[float, float] | None] = [None] * ncols
    for spans in spans_by_row[header_end:]:
        for c0, _, ws in spans:
            r = union(w.rect for w in ws)
            e = extent[c0]
            extent[c0] = (r[0], r[2]) if e is None else (min(e[0], r[0]), max(e[1], r[2]))

    # Extend header cells over the empty columns covered by the rule printed under them.
    for r in range(titles, header_end):
        spans = spans_by_row[r]
        bottom = row_bottoms[r]
        # A rule across the whole table separates header from body; it spans nothing.
        under = [
            x
            for x in rules
            if bottom - 1.5 <= x.y <= ybounds[r + 1] + 3.0
            and x.x1 - x.x0 < 0.9 * (rect[2] - rect[0])
        ]
        for i, (c0, c1, ws) in enumerate(spans):
            left = min(w.rect[0] for w in ws)
            rule = next((x for x in under if x.x0 - 2 <= left <= x.x1), None)
            if rule is None:
                continue
            limit = spans[i + 1][0] if i + 1 < len(spans) else ncols
            end = c1
            for c in range(c1 + 1, limit):
                e = extent[c]
                if e is None or min(rule.x1, e[1]) - max(rule.x0, e[0]) < 0.5 * (e[1] - e[0]):
                    break
                end = c
            spans[i] = (c0, end, ws)

    cells: list[GridCell] = []
    covered: set[tuple[int, int]] = set()
    by_origin: dict[tuple[int, int], GridCell] = {}
    for r, spans in enumerate(spans_by_row):
        role: CellRole = "title" if r < titles else "header" if r < header_end else "body"
        filled = {c: (c0, c1, ws) for c0, c1, ws in spans for c in range(c0, c1 + 1)}
        c = 0
        while c < ncols:
            if (r, c) in covered:
                c += 1
                continue
            if c in filled:
                c0, c1, ws = filled[c]
                cell = GridCell(
                    row=r, col=c0, rect=(0, 0, 0, 0), col_span=c1 - c0 + 1, words=list(ws)
                )
                c = c1 + 1
            else:
                above = by_origin.get((r - 1, c)) if titles < r < header_end else None
                if above is not None and above.words and above.col_span == 1:
                    above.row_span += 1
                    covered.add((r, c))
                    c += 1
                    continue
                cell = GridCell(row=r, col=c, rect=(0, 0, 0, 0))
                c += 1
            cell.role = role
            by_origin[(r, cell.col)] = cell
            cells.append(cell)
    for cell in cells:
        cell.rect = (
            bounds[cell.col],
            ybounds[cell.row],
            bounds[cell.col + cell.col_span],
            ybounds[cell.row + cell.row_span],
        )
        cell.words = []  # `layout.assemble` assigns the words again, by position
    return Grid(
        rect=(rect[0], rect[1], rect[2], ybounds[-1]), rows=len(lines), cols=ncols, cells=cells
    )


def _edges(values: list[float]) -> list[float]:
    """Distinct rule positions, with positions closer than a point taken as one."""
    out: list[float] = []
    for v in sorted(values):
        if not out or v - out[-1] > 1.0:
            out.append(v)
    return out


def _nearest(edges: list[float], v: float) -> int:
    return min(range(len(edges)), key=lambda i: abs(edges[i] - v))


def grid_from_ruling(rows: list[list[Rect | None]]) -> Grid | None:
    """A ruled table's grid from the cells its rules enclose (`find_tables` rows, with None where
    a merged cell covers the slot). The rules decide every cell; the words only fill them.

    Leading rows whose one cell spans the whole table are titles. The first row after them is
    the header, together with the rows its cells span down into.
    """
    boxes = [b for row in rows for b in row if b is not None]
    xs = _edges([v for b in boxes for v in (b[0], b[2])])
    ys = _edges([v for b in boxes for v in (b[1], b[3])])
    ncols, nrows = len(xs) - 1, len(ys) - 1
    if ncols < 2 or nrows < 2:
        return None
    cells: list[GridCell] = []
    taken: set[tuple[int, int]] = set()
    for b in sorted(boxes, key=lambda b: (b[1], b[0])):
        c0, c1 = _nearest(xs, b[0]), _nearest(xs, b[2])
        r0, r1 = _nearest(ys, b[1]), _nearest(ys, b[3])
        if c1 <= c0 or r1 <= r0 or (r0, c0) in taken:
            continue
        taken.update((r, c) for r in range(r0, r1) for c in range(c0, c1))
        cells.append(
            GridCell(
                row=r0,
                col=c0,
                rect=(xs[c0], ys[r0], xs[c1], ys[r1]),
                row_span=r1 - r0,
                col_span=c1 - c0,
            )
        )
    for r in range(nrows):
        for c in range(ncols):
            if (r, c) not in taken:
                cells.append(GridCell(row=r, col=c, rect=(xs[c], ys[r], xs[c + 1], ys[r + 1])))
    origin = {(c.row, c.col): c for c in cells}
    titles = _title_rows(
        [
            (0, cell.col_span - 1)
            if (cell := origin.get((r, 0))) and cell.row_span == 1
            else (-1, -1)
            for r in range(nrows)
        ],
        ncols,
        nrows,
    )
    header_end = titles + max(c.row_span for c in cells if c.row == titles)
    header_end = min(header_end, nrows - 1)
    for cell in cells:
        cell.role = "title" if cell.row < titles else "header" if cell.row < header_end else "body"
    return Grid(rect=(xs[0], ys[0], xs[-1], ys[-1]), rows=nrows, cols=ncols, cells=cells)


def _boundaries(
    n: int, extents: dict[int, tuple[float, float]], lo: float, hi: float
) -> list[float]:
    """Boundaries between n slots, midway between neighbouring slots' extents."""
    known = sorted(extents)
    if not known:
        return [lo + (hi - lo) * i / n for i in range(n + 1)]
    bounds = [lo]
    for i in range(1, n):
        left = max((k for k in known if k < i), default=None)
        right = min((k for k in known if k >= i), default=None)
        if left is not None and right is not None:
            a, b = extents[left][1], extents[right][0]
            share = (i - left) / (right - left + 1) if right - left > 1 else 0.5
            bounds.append(a + (b - a) * share if b > a else (a + b) / 2)
        elif left is not None:
            a = extents[left][1]
            bounds.append(a + (hi - a) * (i - left) / (n - left))
        else:
            assert right is not None
            b = extents[right][0]
            bounds.append(lo + (b - lo) * i / max(right, 1))
    bounds.append(hi)
    for i in range(1, len(bounds)):
        bounds[i] = max(bounds[i], bounds[i - 1])
    return bounds


@dataclass(frozen=True, slots=True)
class CellSpec:
    """A detector's cell: grid position, spans, a text box, and its role in the table."""

    row: int
    col: int
    row_span: int
    col_span: int
    rect: Rect
    role: CellRole


def grid_from_cells(rect: Rect, rows: int, cols: int, specs: list[CellSpec]) -> Grid:
    """A grid whose cells tile `rect`, from a detector's cells (TableFormer gives text boxes,
    not cell boxes, and none for empty cells)."""
    col_ext: dict[int, tuple[float, float]] = {}
    row_ext: dict[int, tuple[float, float]] = {}
    for s in specs:
        if s.rect[2] <= s.rect[0]:
            continue
        if s.col_span == 1:
            e = col_ext.get(s.col)
            col_ext[s.col] = (
                (s.rect[0], s.rect[2])
                if e is None
                else (min(e[0], s.rect[0]), max(e[1], s.rect[2]))
            )
        if s.row_span == 1:
            e = row_ext.get(s.row)
            row_ext[s.row] = (
                (s.rect[1], s.rect[3])
                if e is None
                else (min(e[0], s.rect[1]), max(e[1], s.rect[3]))
            )
    xb = _boundaries(cols, col_ext, rect[0], rect[2])
    yb = _boundaries(rows, row_ext, rect[1], rect[3])
    cells: list[GridCell] = []
    taken: set[tuple[int, int]] = set()
    for s in sorted(specs, key=lambda s: (s.row, s.col)):
        if (s.row, s.col) in taken:
            continue
        rs = max(1, min(s.row_span, rows - s.row))
        cs = max(1, min(s.col_span, cols - s.col))
        for r in range(s.row, s.row + rs):
            for c in range(s.col, s.col + cs):
                taken.add((r, c))
        cells.append(
            GridCell(
                row=s.row,
                col=s.col,
                rect=(xb[s.col], yb[s.row], xb[s.col + cs], yb[s.row + rs]),
                row_span=rs,
                col_span=cs,
                role=s.role,
            )
        )
    for r in range(rows):
        for c in range(cols):
            if (r, c) not in taken:
                cells.append(GridCell(row=r, col=c, rect=(xb[c], yb[r], xb[c + 1], yb[r + 1])))
    return Grid(rect=rect, rows=rows, cols=cols, cells=cells)
