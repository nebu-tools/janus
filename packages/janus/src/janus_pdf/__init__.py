"""Janus: text and layout from PDFs, with the page and box each word was printed in.

    import janus_pdf

    layer = janus_pdf.read("report.pdf")              # text, words, lines, tables, boxes
    (span,) = janus_pdf.find_quote("412 (34.5%)", layer.text)
    anchor = janus_pdf.make_anchor(layer, span)       # the quote, its boxes and table cells
    other = janus_pdf.read("report.pdf", janus_pdf.PdfiumParser())
    janus_pdf.resolve(anchor, other)                  # the same quote in a second engine's layer
    janus_pdf.render_png(pdf_bytes, page=2, scale=2)  # a page image the boxes fit over

`janus_pdf.document` holds the rest of the document layer: OCR, Docling, triage and comparison.
"""

from janus_pdf.document import (
    Anchor,
    Box,
    CellRef,
    DifferentDocument,
    Layer,
    Line,
    NotAPdf,
    Page,
    Parser,
    ParserRecipe,
    PdfiumParser,
    PyMuPDFParser,
    Resolution,
    Span,
    Table,
    TableCell,
    TextQuote,
    Word,
    find_quote,
    make_anchor,
    read,
    render_png,
    resolve,
)

__all__ = [
    "Anchor",
    "Box",
    "CellRef",
    "DifferentDocument",
    "Layer",
    "Line",
    "NotAPdf",
    "Page",
    "Parser",
    "ParserRecipe",
    "PdfiumParser",
    "PyMuPDFParser",
    "Resolution",
    "Span",
    "Table",
    "TableCell",
    "TextQuote",
    "Word",
    "find_quote",
    "make_anchor",
    "read",
    "render_png",
    "resolve",
]
