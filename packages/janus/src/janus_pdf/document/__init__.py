"""Reading a PDF into a layer: words, lines, tables and pages with offsets and boxes.

    layer = read(pdf_bytes)                       # PyMuPDF, the default engine
    layer = read(pdf_bytes, PdfiumParser())       # a second engine for differential checks
    anchor = make_anchor(layer, quote_spans(layer.text, "46.15 ± 14.67")[0])

A layer is immutable and identified by content: `output_hash` is the SHA-256 of its canonical JSON.
Re-reading with another engine gives another layer; `resolve` maps an anchor across layers.
"""

import hashlib
from pathlib import Path

from janus_pdf.canonical import canonical_json
from janus_pdf.document.anchors import (
    RESOLVE_VERSION,
    DifferentDocument,
    boxes_for,
    compare_layers,
    make_anchor,
    page_words,
    quote_spans,
    resolve,
)
from janus_pdf.document.docling import DoclingParser, DoclingUnavailable, docling_available
from janus_pdf.document.engines import PdfiumParser, PyMuPDFParser
from janus_pdf.document.model import (
    Anchor,
    Box,
    CellRef,
    Layer,
    Line,
    Page,
    PageAgreement,
    PageTriage,
    Parser,
    ParserRecipe,
    RawLayer,
    Resolution,
    Table,
    TableCell,
    TextQuote,
    Word,
)
from janus_pdf.document.ocr import OcrMyPdfParser, OcrUnavailable, ocr_available
from janus_pdf.document.quotes import Span, find_quote
from janus_pdf.document.render import render_png
from janus_pdf.document.triage import triage

# Kept from Kittum so recipe hashes of stored layers stay valid across the move.
_RECIPE_DOMAIN = b"kittum.documents.recipe.v1"


class NotAPdf(ValueError):
    """The bytes are not a PDF."""


def recipe_hash(recipe: ParserRecipe) -> str:
    """SHA-256 of a recipe's canonical JSON: equal for parsers that read a PDF the same way."""
    body = canonical_json(recipe.model_dump(mode="json"))
    return hashlib.sha256(_RECIPE_DOMAIN + b"\x00" + body).hexdigest()


def document_hash(pdf: bytes) -> str:
    """SHA-256 of the PDF bytes, which identifies the document every layer of it is read from."""
    return hashlib.sha256(pdf).hexdigest()


def layer_of(pdf: bytes, raw: RawLayer, recipe: ParserRecipe) -> Layer:
    """A `Layer` from a parser's output, with its hashes."""
    body = canonical_json(raw.model_dump(mode="json"))
    return Layer(
        document_hash=document_hash(pdf),
        recipe=recipe,
        recipe_hash=recipe_hash(recipe),
        output_hash=hashlib.sha256(body).hexdigest(),
        **{name: getattr(raw, name) for name in RawLayer.model_fields},
    )


def read(pdf: bytes | Path | str, parser: Parser | None = None) -> Layer:
    """Read a PDF (bytes or a path) with `parser`, PyMuPDF by default."""
    data = pdf if isinstance(pdf, bytes) else Path(pdf).read_bytes()
    if not data.startswith(b"%PDF-"):
        raise NotAPdf("the file does not start with %PDF-")
    parser = parser or PyMuPDFParser()
    return layer_of(data, parser.parse(data), parser.recipe)


__all__ = [
    "RESOLVE_VERSION",
    "Anchor",
    "Box",
    "CellRef",
    "DifferentDocument",
    "DoclingParser",
    "DoclingUnavailable",
    "Layer",
    "Line",
    "NotAPdf",
    "OcrMyPdfParser",
    "OcrUnavailable",
    "Page",
    "PageAgreement",
    "PageTriage",
    "Parser",
    "ParserRecipe",
    "PdfiumParser",
    "PyMuPDFParser",
    "RawLayer",
    "Resolution",
    "Span",
    "Table",
    "TableCell",
    "TextQuote",
    "Word",
    "boxes_for",
    "compare_layers",
    "docling_available",
    "document_hash",
    "find_quote",
    "layer_of",
    "make_anchor",
    "ocr_available",
    "page_words",
    "quote_spans",
    "read",
    "recipe_hash",
    "render_png",
    "resolve",
    "triage",
]
