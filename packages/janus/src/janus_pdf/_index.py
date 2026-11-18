"""One layer indexed for locating: label-normalised text, lookups by offset, and headings.

Locators read the layer through a `View`, the index restricted to the pages a field may look on,
so a field's `pages` applies to every locator in one place.

Building the index walks the whole layer once, which on a long document costs more than
extracting a spec from it. `index_of` keeps the index of the most recent layer, so a spec edited
and run again, or `inspect` followed by `extract`, builds it once.
"""

import bisect
import re
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from statistics import median

from rapidfuzz import fuzz, process

from janus_pdf.document import Box, Layer, Line, Span, TableCell, Word
from janus_pdf.document.layout import Rect, rotate
from janus_pdf.values import clean

SUGGEST_AT = 75  # fuzzy similarity for a suggestion; fuzzy matches never become values

_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2212"), "-")


def _norm_char(ch: str) -> str:
    if ch in "\t\f":
        return ch
    if ch.isspace():
        return " "
    return unicodedata.normalize("NFKC", ch).casefold().translate(_DASHES)


def normalize_label(text: str) -> str:
    """NFKC, case-folded, one kind of dash, single spaces, no trailing colon."""
    out = unicodedata.normalize("NFKC", text).casefold().translate(_DASHES)
    return re.sub(r"\s+", " ", out).strip().rstrip(":").strip()


def rank(line: Line) -> tuple[float, bool]:
    """How prominent a heading is: font size first, then weight."""
    return (round(line.size or 0.0, 1), line.bold)


class Index:
    """Lookups over one layer: label-normalised text, line starts, cells, words and headings."""

    def __init__(self, layer: Layer) -> None:
        self.layer = layer
        chars: list[str] = []
        origin: list[int] = []
        for i, ch in enumerate(layer.text):
            n = _norm_char(ch)
            if n == " " and chars and chars[-1] in " \t\f\n":
                continue
            for c in n:
                chars.append(c)
                origin.append(i)
        self._norm = "".join(chars)
        self._origin = origin
        self._starts = {ln.start for ln in layer.lines} | {c.start for c in layer.cells}
        self._cells = sorted(layer.cells, key=lambda c: c.start)
        self._cell_starts = [c.start for c in self._cells]
        self.words = sorted(layer.words, key=lambda w: w.start)
        self._word_starts = [w.start for w in self.words]
        self._lines = sorted(layer.lines, key=lambda ln: ln.start)
        self._line_starts = [ln.start for ln in self._lines]
        self.page_lines: dict[int, list[Line]] = {p.number: [] for p in layer.pages}
        self.page_words: dict[int, list[Word]] = {p.number: [] for p in layer.pages}
        for w in self.words:
            self.page_words.setdefault(w.box.page, []).append(w)
        for ln in sorted(layer.lines, key=lambda ln: ln.box.y0):
            self.page_lines.setdefault(ln.box.page, []).append(ln)
        self._page_starts = [p.start for p in layer.pages]
        self._pages = {p.number: p for p in layer.pages}
        self.by_table: dict[str, list[TableCell]] = {t.id: [] for t in layer.tables}
        for c in layer.cells:
            self.by_table.setdefault(c.table_id, []).append(c)
        sizes = [ln.size for ln in layer.lines if ln.size and ln.end - ln.start > 20]
        self._body_size = median(sizes) if sizes else None
        self.headings = self._find_headings()
        self._units: list[tuple[int, str]] | None = None
        self._heads: dict[int, list[str]] = {}
        self._views: dict[tuple[int, int] | None, View] = {}
        self._furniture: frozenset[int] | None = None

    def view(self, pages: tuple[int, int] | None) -> "View":
        """The index restricted to pages `pages` (first and last), or to none."""
        if pages not in self._views:
            self._views[pages] = View(self, pages)
        return self._views[pages]

    def upright(self, box: Box) -> Rect:
        """`box` in its page's reading frame: the page as displayed, turned so that its text
        runs left to right. On a page that is not turned this is the box itself."""
        page = self._pages.get(box.page)
        rect = (box.x0, box.y0, box.x1, box.y1)
        if page is None or not page.frame:
            return rect
        return rotate(rect, page.frame, page.width, page.height)

    def frame_height(self, page: int) -> float:
        """The height of `page` in its reading frame."""
        p = self._pages.get(page)
        if p is None:
            return 842.0
        return p.width if p.frame % 180 else p.height

    @property
    def furniture(self) -> frozenset[int]:
        """The start offsets of the lines that may be running heads, running feet and page
        numbers: lines in the top or bottom eighth of a page that a neighbouring page prints at
        the same height with the same text, digits aside, and that are not in a table cell.

        Lines are taken by height, from the top down and from the foot up, while every line at
        that height repeats; the first height that prints anything else ends the run.

        This is a candidate list, never a reason on its own to drop text: "Statement 1" and
        "Statement 2" at the top of two forms qualify. Locators leave these lines out only where
        the spec says text flows over a page break, and report each line they leave out.
        """
        if self._furniture is None:
            keys = {
                ln.start: re.sub(r"\d+", "#", normalize_label(self.text(ln.start, ln.end)))
                for ln in self._lines
            }
            tops = {ln.start: self.upright(ln.box)[1] for ln in self._lines}
            at: dict[tuple[str, int], list[float]] = {}
            for ln in self._lines:
                at.setdefault((keys[ln.start], ln.box.page), []).append(tops[ln.start])

            def repeats(ln: Line) -> bool:
                key, page = keys[ln.start], ln.box.page
                return (
                    bool(key)
                    and self.cell_at(ln.start) is None
                    and any(
                        abs(y - tops[ln.start]) < 2
                        for near in (page - 1, page + 1)
                        for y in at.get((key, near), ())
                    )
                )

            out: set[int] = set()
            for page, lines in self.page_lines.items():
                height = self.frame_height(page)
                margin = height / 8
                bands: list[list[Line]] = []
                for ln in sorted(lines, key=lambda ln: tops[ln.start]):
                    if bands and tops[ln.start] - tops[bands[-1][0].start] < 2:
                        bands[-1].append(ln)
                    else:
                        bands.append([ln])
                heads = (b for b in bands if self.upright(b[0].box)[3] <= margin)
                feet = (b for b in bands[::-1] if tops[b[0].start] >= height - margin)
                for order in (heads, feet):
                    for band in order:
                        if not all(repeats(ln) for ln in band):
                            break
                        out.update(ln.start for ln in band)
            self._furniture = frozenset(out)
        return self._furniture

    def position(self, word: Word) -> int:
        """`word`'s place in reading order."""
        return bisect.bisect_left(self._word_starts, word.start)

    def text(self, start: int, end: int) -> str:
        return self.layer.text[start:end]

    def page_of(self, offset: int) -> int:
        """The number of the page that holds `offset`."""
        i = bisect.bisect_right(self._page_starts, offset) - 1
        return self.layer.pages[max(i, 0)].number if self.layer.pages else 1

    def cell_at(self, offset: int) -> TableCell | None:
        i = bisect.bisect_right(self._cell_starts, offset) - 1
        if i >= 0:
            cell = self._cells[i]
            if cell.start <= offset < max(cell.end, cell.start + 1):
                return cell
        return None

    def line_at(self, offset: int) -> Line | None:
        i = bisect.bisect_right(self._line_starts, offset) - 1
        if i >= 0 and self._lines[i].start <= offset < self._lines[i].end:
            return self._lines[i]
        return None

    def words_between(self, start: int, end: int) -> Iterator[Word]:
        i = bisect.bisect_left(self._word_starts, start)
        while i < len(self.words) and self.words[i].start < end:
            yield self.words[i]
            i += 1

    def find_label(self, label: str) -> Iterator[Span]:
        """Where `label` begins a printed line or a table cell and ends on a token boundary."""
        needle = normalize_label(label)
        text = self.layer.text
        for m in re.finditer(re.escape(needle), self._norm):
            start = self._origin[m.start()]
            end = self._origin[m.end() - 1] + 1
            if start not in self._starts:
                continue
            if end < len(text) and text[end - 1].isalnum() and text[end].isalnum():
                continue
            yield Span(start, end)

    def suggestions(self, label: str, on: Callable[[int], bool] = lambda _: True) -> list[str]:
        """Up to three lines or cells on pages `on` accepts whose opening words come close to
        `label`, best first."""
        needle = normalize_label(label)
        if self._units is None:
            spans = [(ln.start, ln.end) for ln in self.layer.lines] + [
                (c.start, c.end) for c in self.layer.cells if c.end > c.start
            ]
            self._units = [(s, self.text(s, e)) for s, e in spans]
            self._whole = [normalize_label(printed) for _, printed in self._units]
        words = needle.count(" ") + 1
        if words not in self._heads:
            # Each line's opening words, as many as the label has, without a trailing colon.
            self._heads[words] = [" ".join(n.split(" ")[:words]).rstrip(":") for n in self._whole]
        scores: dict[int, float] = {}
        for choices in (self._whole, self._heads[words]):
            for _, score, i in process.extract(
                needle, choices, scorer=fuzz.ratio, score_cutoff=SUGGEST_AT, limit=None
            ):
                scores[i] = max(score, scores.get(i, 0.0))
        best: dict[str, tuple[float, str, int]] = {}
        for i, score in scores.items():
            start, printed = self._units[i]
            n = self._whole[i]
            if not on(self.page_of(start)):
                continue
            if n and n != needle and (n not in best or best[n][0] < score):
                best[n] = (score, clean(printed), self.page_of(start))
        ranked = sorted(best.values(), key=lambda s: (-s[0], s[2], s[1]))[:3]
        return [f"{text!r} on page {page} (similarity {score:.0f})" for score, text, page in ranked]

    def _find_headings(self) -> tuple[Line, ...]:
        """Lines that open a block, are short, and are set larger or bolder than body text."""
        text = self.layer.text
        body = self._body_size
        if body is None:
            return ()
        out = []
        for ln in self._lines:
            if ln.size is None or self.cell_at(ln.start):
                continue
            before = text[max(0, ln.start - 2) : ln.start]
            printed = text[ln.start : ln.end].strip()
            if ln.start and before != "\n\n" and not before.endswith("\f\n"):
                continue
            if not printed or len(printed.split()) > 12 or printed[-1] in ".,;:":
                continue
            if ln.size > body * 1.05 or (ln.bold and ln.size >= body * 0.85):
                out.append(ln)
        return tuple(out)


class View:
    """The index as one field sees it: only the pages the field may look on.

    Every locator reads through a view, so words, tables, headings, label matches and
    suggestions on other pages do not exist for it. Offsets and text are the layer's own.
    """

    def __init__(self, index: Index, pages: tuple[int, int] | None) -> None:
        self.index = index
        self.layer = index.layer
        self.pages = pages
        self.words = [w for w in index.words if self.on(w.box.page)]
        self.tables = tuple(t for t in index.layer.tables if self.on(t.page))
        self.headings = tuple(h for h in index.headings if self.on(h.box.page))
        self.by_table = index.by_table
        self.text = index.text
        self.page_of = index.page_of
        self.cell_at = index.cell_at
        self.line_at = index.line_at
        self.position = index.position
        self.upright = index.upright
        self.numbers = tuple(p.number for p in index.layer.pages if self.on(p.number))
        on = [p for p in index.layer.pages if self.on(p.number)]
        self.end = on[-1].end if on else 0  # where the text of the field's last page ends

    def on(self, page: int) -> bool:
        """Whether the field may look on `page`."""
        return self.pages is None or self.pages[0] <= page <= self.pages[1]

    def find_label(self, label: str) -> Iterator[Span]:
        return (s for s in self.index.find_label(label) if self.on(self.page_of(s.start)))

    def words_between(self, start: int, end: int) -> Iterator[Word]:
        return (w for w in self.index.words_between(start, end) if self.on(w.box.page))

    def suggestions(self, label: str) -> list[str]:
        return self.index.suggestions(label, self.on)

    def lines_on(self, page: int) -> list[Line]:
        """The printed lines of `page`, top to bottom."""
        return self.index.page_lines.get(page, []) if self.on(page) else []

    def words_on(self, page: int) -> list[Word]:
        """The words of `page`, in reading order."""
        return self.index.page_words.get(page, []) if self.on(page) else []

    def place(self, words: Iterable[Word]) -> tuple[Span, ...]:
        """`words` as spans of the layer text in reading order: one span for each run of words
        that follow one another with no other word between them."""
        ordered = sorted(set(words), key=lambda w: w.start)
        spans: list[Span] = []
        last = -2
        for w in ordered:
            pos = self.position(w)
            if spans and pos == last + 1:
                spans[-1] = Span(spans[-1].start, w.end)
            else:
                spans.append(Span(w.start, w.end))
            last = pos
        return tuple(spans)


_LAST: tuple[Layer, Index] | None = None


def index_of(layer: Layer) -> Index:
    """The index of `layer`, built once for the most recent layer asked about.

    The cache is one tuple replaced in a single assignment, so threads that index different
    layers at worst build an index twice; none sees another layer's index.
    """
    global _LAST
    last = _LAST
    if last is not None and last[0] is layer:
        return last[1]
    index = Index(layer)
    _LAST = (layer, index)
    return index
