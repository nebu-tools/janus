"""Janus: typed values from PDFs, each with the page and box it was printed in.

    import janus_pdf

    layer = janus_pdf.read("invoice.pdf")             # text, words, lines, tables, boxes
    spec = janus_pdf.load_spec("invoice.yaml")        # which values, where, of what type
    extraction = janus_pdf.extract(layer, spec)       # each field extracted, or why not
    extraction.data                                   # {"total": {"amount": "627.00", ...}}
    janus_pdf.compare(extraction, reference)          # checks against data typed elsewhere
    janus_pdf.inspect(layer, find="Total due")        # the layer as the locators see it

The document layer underneath:

    (span,) = janus_pdf.find_quote("412 (34.5%)", layer.text)
    anchor = janus_pdf.make_anchor(layer, span)       # the quote, its boxes and table cells
    other = janus_pdf.read("report.pdf", janus_pdf.PdfiumParser())
    janus_pdf.resolve(anchor, other)                  # the same quote in a second engine's layer
    janus_pdf.render_png(pdf_bytes, page=2, scale=2)  # a page image the boxes fit over

`janus_pdf.document` holds the rest of the document layer: OCR, Docling, triage and comparison.
"""

from janus_pdf.compare import Check, Rule, compare
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
from janus_pdf.extract import Extraction, FieldResult, Proposal, Proposer, extract
from janus_pdf.inspect import Inspection, inspect
from janus_pdf.spec import Spec, SpecError
from janus_pdf.spec import load as load_spec
from janus_pdf.values import ParseError, ValueType, parse

__all__ = [
    "Anchor",
    "Box",
    "CellRef",
    "Check",
    "DifferentDocument",
    "Extraction",
    "FieldResult",
    "Inspection",
    "Layer",
    "Line",
    "NotAPdf",
    "Page",
    "ParseError",
    "Parser",
    "ParserRecipe",
    "PdfiumParser",
    "Proposal",
    "Proposer",
    "PyMuPDFParser",
    "Resolution",
    "Rule",
    "Span",
    "Spec",
    "SpecError",
    "Table",
    "TableCell",
    "TextQuote",
    "ValueType",
    "Word",
    "compare",
    "extract",
    "find_quote",
    "inspect",
    "load_spec",
    "make_anchor",
    "parse",
    "read",
    "render_png",
    "resolve",
]
