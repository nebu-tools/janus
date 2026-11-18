"""Helpers shared by the tests: the fixture PDFs, a parser that needs no PDF, and probes that read
a page back with a different engine."""

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

import pymupdf
import pypdfium2

from janus_pdf.document import Box, Layer, ParserRecipe, PyMuPDFParser, RawLayer, layer_of, read
from janus_pdf.document.layout import PageInput, PBlock, PWord, assemble

FIXTURES = Path(__file__).parent / "fixtures"
REPORT = FIXTURES / "survey-report.pdf"  # made by fixtures/make_fixtures.py
INVOICE = FIXTURES / "invoice.pdf"  # labels and borderless line items
ORDER = FIXTURES / "purchase-order.pdf"  # a ruled table under a title row
INSPECTION = FIXTURES / "inspection-report.pdf"  # repeated headings, an "n/a" cell
GUTTER = 297.5  # between the two columns of the report's page 2

# A paragraph that runs from the foot of page 2's left column to the top of its right column,
# with "consis-tent" hyphenated at the line break.
COLUMN_BREAK_QUOTE = (
    "Abundance estimates were directionally consistent across both sites and agreed with the "
    "counts from the earlier survey of the same"
)
# "resid-ing" is broken with a soft hyphen (U+00AD).
SOFT_HYPHEN_QUOTE = "under stones, residing in the fastest"


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def text_under(pdf: bytes, box: Box) -> str:
    """What PDFium (not the engine that made the box) reads inside a box.

    Probes the middle half of the box across the text direction: line boxes run from ascender to
    descender, so the tall letters of the neighbouring line reach into them.
    """
    doc = pypdfium2.PdfDocument(pdf)
    page = doc[box.page - 1]
    left, _, _, top = page.get_cropbox()
    textpage = page.get_textpage()
    x0, y0, x1, y1 = box.x0, box.y0, box.x1, box.y1
    if x1 - x0 < y1 - y0:  # a sideways line
        x0, x1 = x0 + (x1 - x0) / 4, x1 - (x1 - x0) / 4
    else:
        y0, y1 = y0 + (y1 - y0) / 4, y1 - (y1 - y0) / 4
    text = textpage.get_text_bounded(left=left + x0, bottom=top - y1, right=left + x1, top=top - y0)
    textpage.close()
    page.close()
    doc.close()
    return squash(text.replace("­", "-").replace("\x02", "-").replace("￾", "-"))


def ink(png: bytes, box: Box, scale: float) -> float:
    """Share of dark pixels inside a box on a rendered page."""
    pixmap = pymupdf.Pixmap(png)
    x0, y0 = int(box.x0 * scale), int(box.y0 * scale)
    x1, y1 = int(box.x1 * scale), int(box.y1 * scale)
    dark = total = 0
    for y in range(max(y0, 0), min(y1, pixmap.height)):
        for x in range(max(x0, 0), min(x1, pixmap.width)):
            r, g, b = pixmap.pixel(x, y)[:3]
            total += 1
            dark += (r + g + b) / 3 < 128
    return dark / total if total else 0.0


_CHAR = 5.0  # points per character
_LEADING = 12.0


class TextParser:
    """Lays out the given page texts in a fixed-width grid on A4 pages: one block per paragraph
    (blank line), one printed line per text line. It ignores the PDF bytes it is given."""

    def __init__(self, pages: list[str], *, name: str = "text") -> None:
        self._pages = pages
        self.recipe = ParserRecipe(engine=f"fake-{name}", engine_version="1")

    def parse(self, pdf: bytes) -> RawLayer:  # noqa: ARG002 - the parser protocol
        inputs = []
        for number, text in enumerate(self._pages, start=1):
            blocks: list[PBlock] = []
            y = 72.0
            for paragraph in text.split("\n\n"):
                lines = []
                for raw in paragraph.splitlines():
                    x = 72.0
                    words = []
                    for token in raw.split():
                        words.append(PWord(text=token, rect=(x, y, x + _CHAR * len(token), y + 10)))
                        x += _CHAR * (len(token) + 1)
                    if words:
                        lines.append(words)
                    y += _LEADING
                if lines:
                    blocks.append(PBlock(lines=lines))
                y += _LEADING
            inputs.append(
                PageInput(number=number, width=595.0, height=842.0, rotation=0, blocks=blocks)
            )
        return assemble(inputs)


def text_layer(text: str, *, name: str = "text", pdf: bytes = b"%PDF-1.7 fake") -> Layer:
    """A one-page layer of `text` laid out by `TextParser`, as a layer of the PDF `pdf`."""
    parser = TextParser([text], name=name)
    return layer_of(pdf, parser.parse(pdf), parser.recipe)


LEDGER = FIXTURES / "stock-ledger.pdf"  # a ruled table over three pages
PACKING = FIXTURES / "packing-list.pdf"  # the header Item / Qty printed again, five ways

Item = (
    tuple[float, float, str]
    | tuple[float, float, str, float]
    | tuple[float, float, str, float, bool]
)


def drawn(
    *pages: Sequence[Item],
    rules: Mapping[int, Sequence[tuple[float, float, float, float]]] | None = None,
    rotation: int = 0,
) -> Layer:
    """A layer read with PyMuPDF from an A4 PDF of `pages`, each a list of (x, baseline y, text),
    (x, y, text, font size) or (x, y, text, font size, bold), in Helvetica. `rules` draws lines (x0, y0, x1, y1) on a page by
    its number; `rotation` turns every page, with the text placed in unrotated coordinates."""
    doc = pymupdf.open()
    for number, items in enumerate(pages, start=1):
        page = doc.new_page(width=595, height=842)
        for item in items:
            x, y, text, *style = item
            size, bold = style[0] if style else 11, len(style) > 1 and bool(style[1])
            page.insert_text((x, y), text, fontsize=size, fontname="hebo" if bold else "helv")
        for x0, y0, x1, y1 in (rules or {}).get(number, []):
            page.draw_line((x0, y0), (x1, y1), width=0.6)
        if rotation:
            page.set_rotation(rotation)
    data = doc.tobytes()
    doc.close()
    return read(data, PyMuPDFParser())
