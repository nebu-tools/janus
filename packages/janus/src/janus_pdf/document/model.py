"""The document model: what a parser reads from a PDF, and anchors into it.

Offsets are Unicode code points, half-open, over a layer's NFC text. Boxes are in PDF points on
the page as displayed, after its /Rotate, with the origin at the displayed crop box's top-left
corner, so they lie over the page image `render_png` draws. Pages are 1-based.

Everything is identified by content. A document is the SHA-256 of its bytes. A layer's `id` is the
SHA-256 of the document hash, the recipe and the canonical JSON of what the parser read, so two
layers share an id only when they are the same reading of the same file by the same recipe. An
application that stores layers in a database keeps its own row identifiers beside these hashes.
"""

from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, StringConstraints

type Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PageKind = Literal["text", "ocr", "broken_encoding"]
# A title row spans the whole table above its header; it heads no column.
CellRole = Literal["title", "header", "body"]
ResolutionStatus = Literal["exact", "candidate", "ambiguous", "unresolved"]


class Record(BaseModel):
    """An immutable value. Unknown fields are rejected, so typos fail loudly."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ParserRecipe(Record):
    """Everything that decides a parser's output: engine, version, model weights, settings."""

    engine: str  # "pymupdf", "pypdfium2", "docling", ...
    engine_version: str
    container_digest: str | None = None
    weights: tuple[tuple[str, Sha256], ...] = ()
    settings: tuple[tuple[str, str], ...] = ()


class Box(Record):
    """A rectangle on a page as displayed, in points from the crop box's top-left corner."""

    page: int  # 1-based
    x0: float
    y0: float
    x1: float
    y1: float


class Word(Record):
    """A word's slice of the layer text and where it is printed."""

    start: int
    end: int
    box: Box


class Line(Record):
    """One printed line, or one line inside a table cell."""

    start: int
    end: int
    box: Box
    size: float | None = None  # the largest font size on the line, in points, when known
    bold: bool = False  # every word on the line is set in a bold face


class PageTriage(Record):
    """Whether a page's text layer can be trusted."""

    page: int
    kind: PageKind
    reasons: tuple[str, ...] = ()


class Page(Record):
    """A page's size and turn, and its slice of the layer text."""

    number: int  # 1-based
    width: float  # as displayed
    height: float
    rotation: int = 0  # the PDF's /Rotate: degrees clockwise the page is turned for display
    frame: int = 0  # degrees clockwise the displayed page turns so most text reads left to right
    label: str | None = None  # printed page label, when the PDF has one
    start: int  # this page's slice of the layer text
    end: int
    triage: PageTriage | None = None


class Table(Record):
    """A table found on a page, and its slice of the layer text."""

    id: str  # "p5t0": page 5, first table in reading order
    page: int
    box: Box
    rows: int
    cols: int
    start: int
    end: int


class TableCell(Record):
    """One cell of a table: its grid position, spans, text slice, box and headers."""

    table_id: str
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    start: int  # an empty cell has start == end
    end: int
    box: Box
    role: CellRole = "body"
    header_path: tuple[str, ...] = ()  # column headers above this cell, outermost first


class RawLayer(Record):
    """What a parser returns. `janus_pdf.document.read` turns it into a `Layer`."""

    text: str
    words: tuple[Word, ...]
    cells: tuple[TableCell, ...] = ()
    lines: tuple[Line, ...] = ()
    pages: tuple[Page, ...] = ()
    tables: tuple[Table, ...] = ()


class Layer(Record):
    """One parser recipe's immutable reading of one document."""

    id: Sha256  # SHA-256 of the document hash, the recipe and the RawLayer's canonical JSON
    document_hash: Sha256
    recipe: ParserRecipe
    text: str
    words: tuple[Word, ...]
    cells: tuple[TableCell, ...] = ()
    lines: tuple[Line, ...] = ()
    pages: tuple[Page, ...] = ()
    tables: tuple[Table, ...] = ()


class TextQuote(Record):
    """The quoted text with some text on either side, to find it again in another layer."""

    exact: str
    prefix: str = ""
    suffix: str = ""


class CellRef(Record):
    """The table cell an anchor touches, by position and column headers."""

    table_id: str
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    header_path: tuple[str, ...] = ()


class Anchor(Record):
    """A span of a layer's text, with the boxes it covers on the page and the cells it touches."""

    layer: Sha256  # the layer's id
    document: Sha256
    quote: TextQuote
    start: int
    end: int
    boxes: tuple[Box, ...]  # one per printed line the quote touches
    cells: tuple[CellRef, ...] = ()


class Resolution(Record):
    """Where an anchor landed in another layer, and how sure the match is."""

    status: ResolutionStatus
    anchor: Anchor | None
    method: str  # "same_layer", "quote", "quote_in_region", "fuzzy", "none"
    method_version: str
    alternatives: tuple[Anchor, ...] = ()  # every match, when the status is "ambiguous"


class Parser(Protocol):
    """Reads PDF bytes into a `RawLayer`; `recipe` names everything that decides the output."""

    recipe: ParserRecipe

    def parse(self, pdf: bytes) -> RawLayer: ...


class PageAgreement(Record):
    """How closely two layers of the same PDF agree on one page."""

    page: int
    words_a: int
    words_b: int
    text_similarity: float  # 0..1 over the word sequences
    box_iou: float  # median IoU of the boxes of words both layers read identically
