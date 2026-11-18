"""Parsers: PyMuPDF (the base layer) and pypdfium2 (the second engine for differential checks).

Both read words in the unrotated page, turn them into the page's reading frame and hand them to
`layout.assemble`, which writes the canonical text and maps boxes to the page as displayed.
"""

import ctypes
import math
from functools import cache
from typing import NamedTuple

import pymupdf
import pypdfium2
import pypdfium2.raw as pdfium_c
from pypdfium2.version import PDFIUM_INFO, PYPDFIUM_INFO

from janus_pdf.document.layout import (
    ASSEMBLY_VERSION,
    Grid,
    PageInput,
    PBlock,
    PWord,
    Rect,
    assemble,
    contains,
    reading_frame,
    rotate,
)
from janus_pdf.document.model import ParserRecipe, RawLayer
from janus_pdf.document.tables import (
    TABLES_VERSION,
    caption_regions,
    grid_from_ruling,
    grid_from_words,
    horizontal_rules,
)
from janus_pdf.document.triage import TRIAGE_VERSION, triage


class _Char(NamedTuple):
    text: str
    rect: Rect
    angle: float
    size: float
    bold: bool


# Word extraction without TEXT_PRESERVE_LIGATURES, so "ﬁ" arrives as "fi".
_WORD_FLAGS = pymupdf.TEXTFLAGS_WORDS & ~pymupdf.TEXT_PRESERVE_LIGATURES


@cache
def _quiet() -> None:
    # PyMuPDF prints a recommendation for its Layout package on first table detection.
    pymupdf.no_recommend_layout()


def _unrotated_size(page: pymupdf.Page) -> tuple[float, float]:
    w, h = page.rect.width, page.rect.height
    return (h, w) if page.rotation % 180 else (w, h)


def pymupdf_frame(page: pymupdf.Page, layout: dict | None = None) -> int:
    """The page's reading frame from PyMuPDF's line directions (reported unrotated)."""
    layout = layout or page.get_text("dict", flags=_WORD_FLAGS)
    directions = [
        (line["dir"][0], line["dir"][1], sum(len(s["text"]) for s in line["spans"]))
        for block in layout["blocks"]
        for line in block.get("lines", ())
    ]
    return reading_frame(directions)


_BOLD = 1 << 4  # PyMuPDF span flag


def _fonts(layout: dict) -> dict[tuple[int, int], tuple[float, bool]]:
    """(block, line) -> (largest font size, all spans bold), from PyMuPDF's dict output."""
    out = {}
    for b, block in enumerate(layout["blocks"]):
        for n, line in enumerate(block.get("lines", ())):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if spans:
                out[(block.get("number", b), n)] = (
                    max(s["size"] for s in spans),
                    all(s["flags"] & _BOLD or "bold" in s["font"].casefold() for s in spans),
                )
    return out


def pymupdf_blocks(page: pymupdf.Page, frame: int, layout: dict | None = None) -> list[PBlock]:
    """Words grouped by PyMuPDF's own blocks and lines, turned into the reading frame."""
    width, height = _unrotated_size(page)
    fonts = _fonts(layout or page.get_text("dict", flags=_WORD_FLAGS))
    blocks: dict[int, dict[int, list[PWord]]] = {}
    for x0, y0, x1, y1, text, block_no, line_no, _ in page.get_text("words", flags=_WORD_FLAGS):
        rect = rotate((x0, y0, x1, y1), frame, width, height)
        size, bold = fonts.get((block_no, line_no), (None, False))
        word = PWord(text=text, rect=rect, size=size, bold=bold)
        blocks.setdefault(block_no, {}).setdefault(line_no, []).append(word)
    return [PBlock(lines=[lines[k] for k in sorted(lines)]) for _, lines in sorted(blocks.items())]


def _segments(page: pymupdf.Page, frame: int) -> list[Rect]:
    """Stroked lines and filled rectangles, turned into the reading frame."""
    width, height = _unrotated_size(page)
    out: list[Rect] = []
    for drawing in page.get_drawings():
        for item in drawing.get("items", ()):
            if item[0] == "l":
                p, q = item[1], item[2]
                r = (min(p.x, q.x), min(p.y, q.y), max(p.x, q.x), max(p.y, q.y))
            elif item[0] == "re":
                r = tuple(item[1])
            else:
                continue
            out.append(rotate((r[0], r[1], r[2], r[3]), frame, width, height))
    return out


def pymupdf_grids(page: pymupdf.Page, blocks: list[PBlock], frame: int) -> list[Grid]:
    """Ruled tables from `find_tables` without the Layout model, whose rules give the cells, and
    three-rule tables found from their captions, whose words give the cells."""
    _quiet()
    width, height = _unrotated_size(page)
    segments = _segments(page, frame)
    rules = horizontal_rules(segments)
    regions = caption_regions(blocks, rules)
    words = [w for b in blocks for line in b.lines for w in line]
    grids: list[Grid] = []
    # A ruled table needs vertical edges: stroked verticals or the sides of filled rectangles.
    # Most pages have none, and find_tables is the slowest step of reading a page.
    verticals = sum(
        1 for r in segments if r[3] - r[1] > 2 and (r[2] - r[0] < 1.5 or r[2] - r[0] > 2)
    )
    try:
        # find_tables reads the page as drawn, so it only helps when no turn is needed.
        found = page.find_tables(use_layout=False).tables if frame == 0 and verticals >= 2 else []
    except (AttributeError, ValueError, RuntimeError):
        found = []
    for table in found:
        rows = [
            [None if c is None else rotate(tuple(c), frame, width, height) for c in row.cells]
            for row in table.rows
        ]
        grid = grid_from_ruling(rows)
        if grid is not None and any(contains(grid.rect, w.cx, w.cy) for w in words):
            grids.append(grid)
    # Where a table is ruled, its rules decide the cells, even when it also has a caption.
    for region in regions:
        if any(_overlap(region, g.rect) for g in grids):
            continue
        inside = [w for w in words if contains(region, w.cx, w.cy)]
        grid = grid_from_words(region, inside, rules) if inside else None
        if grid is not None:
            grids.append(grid)
    return grids


def _overlap(a: Rect, b: Rect) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def pymupdf_page_input(page: pymupdf.Page, *, with_tables: bool = True) -> PageInput:
    layout = page.get_text("dict", flags=_WORD_FLAGS)
    frame = pymupdf_frame(page, layout)
    width, height = _unrotated_size(page)
    if frame % 180:
        width, height = height, width
    blocks = pymupdf_blocks(page, frame, layout)
    return PageInput(
        number=page.number + 1,  # ty: ignore[unsupported-operator]
        width=width,
        height=height,
        rotation=page.rotation,
        frame=(frame - page.rotation) % 360,  # from the page as displayed
        label=page.get_label() or None,
        blocks=blocks,
        grids=pymupdf_grids(page, blocks, frame) if with_tables else [],
    )


class PyMuPDFParser:
    """The base layer: PyMuPDF characters, Janus's reading order and table grids."""

    def __init__(self) -> None:
        self.recipe = ParserRecipe(
            engine="pymupdf",
            engine_version=f"{pymupdf.VersionBind} (MuPDF {pymupdf.VersionFitz})",
            settings=(
                ("assembly", ASSEMBLY_VERSION),
                ("tables", TABLES_VERSION),
                ("find_tables.use_layout", "false"),
                ("triage", TRIAGE_VERSION),
            ),
        )

    def parse(self, pdf: bytes) -> RawLayer:
        """Raises `ValueError` when MuPDF cannot load part of a page: what it would read is not
        the whole page. A cross-reference table it repairs is no reason to refuse the file."""
        shown = pymupdf.TOOLS.mupdf_display_errors()
        pymupdf.TOOLS.mupdf_display_errors(False)
        pymupdf.TOOLS.reset_mupdf_warnings()
        try:
            pages = triage(pdf)
            with pymupdf.open(stream=pdf, filetype="pdf") as doc:
                inputs = []
                for page in doc:
                    page_input = pymupdf_page_input(page)
                    page_input.triage = pages[page_input.number - 1]
                    inputs.append(page_input)
            lost = [
                w for w in pymupdf.TOOLS.mupdf_warnings().splitlines() if w.startswith("cannot")
            ]
        finally:
            pymupdf.TOOLS.mupdf_display_errors(shown)
        if lost:
            raise ValueError(f"MuPDF cannot load all of it ({lost[0]})")
        return assemble(inputs)


def _pdfium_char(textpage: pypdfium2.PdfTextPage, i: int) -> str:
    code = pdfium_c.FPDFText_GetUnicode(textpage, i)
    if code == 2:  # PDFium marks a hyphen it found at a line end as U+0002
        return "-"
    if code in (0xFFFE, 0xFFFF) or (code < 32 and code not in (9, 10, 13)):
        return ""
    return chr(code)


_BOLD_WEIGHT = 600


_FORCE_BOLD = 1 << 18  # the font descriptor's ForceBold flag


def _pdfium_bold(textpage: pypdfium2.PdfTextPage, i: int) -> bool:
    """Bold by the font's weight, its ForceBold flag or its name, as PyMuPDF decides it. PDFium
    reports weight 400 when the font descriptor gives none, so the name has the last word."""
    if pdfium_c.FPDFText_GetFontWeight(textpage, i) >= _BOLD_WEIGHT:
        return True
    name = ctypes.create_string_buffer(128)
    flags = ctypes.c_int()
    pdfium_c.FPDFText_GetFontInfo(textpage, i, name, len(name), ctypes.byref(flags))
    return bool(flags.value & _FORCE_BOLD) or b"bold" in name.value.lower()


def _pdfium_scale(textpage: pypdfium2.PdfTextPage, i: int) -> float:
    """How much the character's matrix scales its font size: PDFium reports the size set by
    `Tf`, which a producer may leave at 1 and scale with the text matrix instead."""
    m = pdfium_c.FS_MATRIX()
    if not pdfium_c.FPDFText_GetMatrix(textpage, i, ctypes.byref(m)):
        return 1.0
    return math.sqrt(abs(m.a * m.d - m.b * m.c)) or 1.0


def _pdfium_chars(page: pypdfium2.PdfPage) -> list[_Char]:
    """Each character with its loose box in the unrotated top-left frame, its angle, its font
    size and whether it is bold."""
    left, _, _, top = page.get_cropbox()
    textpage = page.get_textpage()
    try:
        return _chars_of(textpage, left, top)
    finally:
        textpage.close()


def _chars_of(textpage: pypdfium2.PdfTextPage, left: float, top: float) -> list[_Char]:
    chars: list[_Char] = []
    for i in range(textpage.count_chars()):
        ch = _pdfium_char(textpage, i)
        if ch and not ch.isspace():
            cx0, cy0, cx1, cy1 = textpage.get_charbox(i, loose=True)
            angle = pdfium_c.FPDFText_GetCharAngle(textpage, i)
            size = pdfium_c.FPDFText_GetFontSize(textpage, i) * _pdfium_scale(textpage, i)
            rect = (cx0 - left, top - cy1, cx1 - left, top - cy0)
            chars.append(_Char(ch, rect, angle, size, _pdfium_bold(textpage, i)))
        else:
            chars.append(_Char(ch, (0.0, 0.0, 0.0, 0.0), 0.0, 0.0, False))
    return chars


def pdfium_page_input(page: pypdfium2.PdfPage, number: int) -> PageInput:
    """Characters joined into words, lines, and blocks in content order, in the reading frame."""
    left, bottom, right, top = page.get_cropbox()
    width, height = right - left, top - bottom
    chars = _pdfium_chars(page)
    # PDFium's angle turns clockwise in PDF space (y up), which is counter-clockwise once y
    # points down, so the baseline direction in the frame is (cos, sin).
    frame = reading_frame(
        [(math.cos(a), math.sin(a), 1) for ch, _, a, _, _ in chars if ch and not ch.isspace()]
    )
    lines: list[list[PWord]] = []
    line: list[PWord] = []
    line_rect: list[float] | None = None
    word_chars: list[str] = []
    word_rect: list[float] | None = None
    word_size = 0.0
    word_bold = True
    last_x0 = 0.0

    def grow(acc: list[float] | None, r: Rect) -> list[float]:
        if acc is None:
            return list(r)
        return [min(acc[0], r[0]), min(acc[1], r[1]), max(acc[2], r[2]), max(acc[3], r[3])]

    def end_word() -> None:
        nonlocal word_chars, word_rect, word_size, word_bold
        if word_chars and word_rect is not None:
            r = word_rect
            line.append(
                PWord(
                    text="".join(word_chars),
                    rect=(r[0], r[1], r[2], r[3]),
                    size=word_size or None,
                    bold=word_bold,
                )
            )
        word_chars, word_rect, word_size, word_bold = [], None, 0.0, True

    def end_line() -> None:
        nonlocal line, line_rect
        end_word()
        if line:
            lines.append(line)
        line, line_rect = [], None

    for ch, unrotated, _, size, bold in chars:
        if ch in ("\r", "\n"):
            end_line()
            continue
        if not ch or ch.isspace():
            end_word()
            continue
        rect: Rect = rotate(unrotated, frame, width, height)
        h = max(rect[3] - rect[1], 0.1)
        if line_rect is not None:
            overlap = min(line_rect[3], rect[3]) - max(line_rect[1], rect[1])
            if overlap < 0.5 * min(h, line_rect[3] - line_rect[1]) or rect[0] < last_x0 - h:
                end_line()
            elif word_rect is not None and rect[0] - word_rect[2] > 0.1 * h:
                end_word()
        word_chars.append(ch)
        word_size = max(word_size, size)
        word_bold = word_bold and bold
        word_rect = grow(word_rect, rect)
        line_rect = grow(line_rect, rect)
        last_x0 = rect[0]
    end_line()

    blocks: list[PBlock] = []
    for ln in lines:
        x0 = min(w.rect[0] for w in ln)
        x1 = max(w.rect[2] for w in ln)
        y0 = min(w.rect[1] for w in ln)
        h = max(w.rect[3] for w in ln) - y0
        if blocks:
            prev = blocks[-1].lines[-1]
            px0 = min(w.rect[0] for w in prev)
            px1 = max(w.rect[2] for w in prev)
            gap = y0 - max(w.rect[3] for w in prev)
            if -0.5 * h <= gap < 0.7 * h and min(x1, px1) > max(x0, px0):
                blocks[-1].lines.append(ln)
                continue
        blocks.append(PBlock(lines=[ln]))
    if frame % 180:
        width, height = height, width
    return PageInput(
        number=number,
        width=width,
        height=height,
        rotation=page.get_rotation(),
        frame=(frame - page.get_rotation()) % 360,  # from the page as displayed
        blocks=blocks,
    )


class PdfiumParser:
    """PDFium characters through the same assembly, with font sizes and weights; no table
    detection."""

    def __init__(self) -> None:
        self.recipe = ParserRecipe(
            engine="pypdfium2",
            engine_version=f"pypdfium2 {PYPDFIUM_INFO} (PDFium {PDFIUM_INFO})",
            settings=(("assembly", ASSEMBLY_VERSION), ("charbox", "loose"), ("fonts", "pdfium.v1")),
        )

    def parse(self, pdf: bytes) -> RawLayer:
        doc = pypdfium2.PdfDocument(pdf)
        try:
            inputs = []
            for index in range(len(doc)):
                page = doc[index]
                try:
                    inputs.append(pdfium_page_input(page, index + 1))
                finally:
                    page.close()
        finally:
            doc.close()
        return assemble(inputs)
