"""Reading a PDF into a layer: words, lines, tables and pages with offsets and boxes.

    layer = read(pdf_bytes)                       # PyMuPDF, the default engine
    layer = read(pdf_bytes, PdfiumParser())       # a second engine for differential checks
    anchor = make_anchor(layer, quote_spans(layer.text, "46.15 ± 14.67")[0])

A layer is immutable and identified by content: `id` hashes the document, the recipe and the output.
Re-reading with another engine gives another layer; `resolve` maps an anchor across layers.
"""

import hashlib
from pathlib import Path

import pymupdf

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
    CellRole,
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
_LAYER_DOMAIN = b"janus.layer.v1"


class UnreadablePdf(ValueError):
    """The file cannot be read into a layer. Nothing is guessed from it."""


class NotAPdf(UnreadablePdf):
    """The bytes are not a PDF, or a PDF too damaged to open."""


class EncryptedPdf(UnreadablePdf):
    """The PDF is encrypted and opens only with a password."""


class EmptyPdf(UnreadablePdf):
    """The PDF has no pages."""


def _check(pdf: bytes) -> int:
    """Refuse a file no parser can read completely, before any parser runs. Its page count."""
    if not pdf.startswith(b"%PDF-"):
        raise NotAPdf("the file does not start with %PDF-")
    try:
        doc = pymupdf.open(stream=pdf, filetype="pdf")
    except (RuntimeError, ValueError) as e:
        raise NotAPdf(f"the PDF cannot be opened: {e}") from e
    with doc:
        if doc.needs_pass:
            raise EncryptedPdf("the PDF is encrypted and needs a password to open")
        if doc.page_count == 0:
            raise EmptyPdf("the PDF has no pages")
        return doc.page_count


def page_count(pdf: bytes | Path | str) -> int:
    """How many pages a PDF (bytes or a path) has, without reading them.

    Raises what `read` raises for a file that cannot be opened: `NotAPdf`, `EncryptedPdf` or
    `EmptyPdf`.
    """
    return _check(pdf if isinstance(pdf, bytes) else Path(pdf).read_bytes())


def recipe_hash(recipe: ParserRecipe) -> str:
    """SHA-256 of a recipe's canonical JSON: equal for parsers that read a PDF the same way."""
    body = canonical_json(recipe.model_dump(mode="json"))
    return hashlib.sha256(_RECIPE_DOMAIN + b"\x00" + body).hexdigest()


def document_hash(pdf: bytes) -> str:
    """SHA-256 of the PDF bytes, which identifies the document every layer of it is read from."""
    return hashlib.sha256(pdf).hexdigest()


def layer_id(document: str, recipe: ParserRecipe, raw: RawLayer) -> str:
    """The identity of one recipe's reading of one document: equal only when all three are."""
    body = canonical_json(raw.model_dump(mode="json"))
    parts = (_LAYER_DOMAIN, document.encode(), recipe_hash(recipe).encode(), body)
    return hashlib.sha256(b"\x00".join(parts)).hexdigest()


def layer_of(pdf: bytes, raw: RawLayer, recipe: ParserRecipe) -> Layer:
    """A `Layer` from a parser's output, identified by document, recipe and output."""
    document = document_hash(pdf)
    return Layer(
        id=layer_id(document, recipe, raw),
        document_hash=document,
        recipe=recipe,
        **{name: getattr(raw, name) for name in RawLayer.model_fields},
    )


def read(pdf: bytes | Path | str, parser: Parser | None = None) -> Layer:
    """Read a PDF (bytes or a path) with `parser`, PyMuPDF by default.

    Raises `NotAPdf`, `EncryptedPdf` or `EmptyPdf` (all `UnreadablePdf`) for a file that cannot
    be read completely, including one whose pages the parser cannot load whole. A PDF encrypted only against editing opens without a password and reads.
    """
    data = pdf if isinstance(pdf, bytes) else Path(pdf).read_bytes()
    _check(data)
    parser = parser or PyMuPDFParser()
    try:
        raw = parser.parse(data)
    except UnreadablePdf:
        raise
    except Exception as exc:  # a parser's own error on a damaged file
        raise NotAPdf(f"the PDF cannot be read: {exc}") from exc
    return layer_of(data, raw, parser.recipe)


__all__ = [
    "RESOLVE_VERSION",
    "Anchor",
    "Box",
    "CellRef",
    "CellRole",
    "DifferentDocument",
    "DoclingParser",
    "DoclingUnavailable",
    "EmptyPdf",
    "EncryptedPdf",
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
    "UnreadablePdf",
    "Word",
    "boxes_for",
    "compare_layers",
    "docling_available",
    "document_hash",
    "find_quote",
    "layer_id",
    "layer_of",
    "make_anchor",
    "ocr_available",
    "page_count",
    "page_words",
    "quote_spans",
    "read",
    "recipe_hash",
    "render_png",
    "resolve",
    "triage",
]
