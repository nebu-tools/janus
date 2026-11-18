"""Anchors made on one layer, re-anchored onto a layer from another engine or of other text."""

import pymupdf
import pytest

from janus_pdf.document import (
    RESOLVE_VERSION,
    Anchor,
    DifferentDocument,
    DoclingParser,
    Layer,
    PdfiumParser,
    PyMuPDFParser,
    Span,
    compare_layers,
    docling_available,
    find_quote,
    make_anchor,
    read,
    resolve,
)
from support import COLUMN_BREAK_QUOTE, REPORT, SOFT_HYPHEN_QUOTE, squash, text_layer, text_under

REPEATED = "1.0 (1.0, 2.0)"  # printed three times in one row of Table 1
QUOTES = [
    COLUMN_BREAK_QUOTE,  # across a column break and a hyphenated line break
    SOFT_HYPHEN_QUOTE,  # across a soft hyphen
    "412 (34.5%)",  # a table cell
    "Site A (n = 120)",  # a header spanning three columns
]


def _anchors(layer: Layer, quotes: list[str]) -> list[Anchor]:
    return [make_anchor(layer, span) for quote in quotes for span in find_quote(quote, layer.text)]


def _sideways_pdf() -> bytes:
    """Pages 2 and 3 drawn sideways on landscape pages, with no /Rotate."""
    sideways = pymupdf.open()
    source = pymupdf.open(REPORT)
    for number in (1, 2):
        rect = source[number].rect
        landscape = sideways.new_page(width=rect.height, height=rect.width)
        landscape.show_pdf_page(landscape.rect, source, number, rotate=90)
    return sideways.tobytes()


def test_anchors_survive_a_reparse_with_pdfium(report, report_pdfium):
    anchors = _anchors(report, [*QUOTES, REPEATED])
    assert len(anchors) == len(QUOTES) + 3

    for anchor in anchors:
        resolution = resolve(anchor, report_pdfium)
        assert resolution.status == "exact", anchor.quote.exact
        moved = resolution.anchor
        assert moved is not None and moved.layer == report_pdfium.output_hash
        assert squash(report_pdfium.text[moved.start : moved.end]) == squash(anchor.quote.exact)
        assert [b.page for b in moved.boxes] == [b.page for b in anchor.boxes]
        for old, new in zip(anchor.boxes, moved.boxes, strict=True):
            assert abs(old.x0 - new.x0) < 2 and abs(old.y0 - new.y0) < 2
    repeated = [a for a in anchors if a.quote.exact == REPEATED]
    assert {resolve(a, report_pdfium).method for a in repeated} == {"quote_in_region"}


def test_moved_repeated_changed_and_respelled_quotes(report, report_pdfium):
    (count,) = _anchors(report, ["412 (34.5%)"])
    # As if the old layer had placed the value on page 1: the only match is elsewhere.
    elsewhere = tuple(b.model_copy(update={"page": 1}) for b in count.boxes)
    moved = resolve(count.model_copy(update={"boxes": elsewhere}), report_pdfium)
    assert (moved.status, moved.method) == ("candidate", "quote")

    first, *_ = _anchors(report, [REPEATED])
    lost = resolve(first.model_copy(update={"boxes": elsewhere}), report_pdfium)
    assert lost.status == "ambiguous" and lost.anchor is None
    assert len(lost.alternatives) == 3

    changed = count.model_copy(
        update={"quote": count.quote.model_copy(update={"exact": "413 (34.5%)"})}
    )
    assert resolve(changed, report_pdfium).status == "unresolved"  # a changed number never matches

    (soft,) = _anchors(report, [SOFT_HYPHEN_QUOTE])
    respelled = soft.model_copy(
        update={
            "quote": soft.quote.model_copy(update={"exact": "under stones residing in the fastest"})
        }
    )
    fuzzy = resolve(respelled, report_pdfium)
    assert (fuzzy.status, fuzzy.method) == ("candidate", "fuzzy")
    assert fuzzy.anchor is not None
    assert "stones" in report_pdfium.text[fuzzy.anchor.start : fuzzy.anchor.end]


def test_pymupdf_and_pdfium_agree_on_every_page(report, report_pdfium):
    agreement = compare_layers(report, report_pdfium)
    assert len(agreement) == 4
    for page in agreement:
        assert page.text_similarity > 0.9, page
        assert page.box_iou > 0.9, page


def test_turned_pages_read_in_order_with_boxes_in_the_unrotated_frame(report):
    (span,) = find_quote("412 (34.5%)", report.text)
    (expected,) = make_anchor(report, span).boxes

    # An upright page the viewer turns with /Rotate 90: boxes stay where they were drawn.
    doc = pymupdf.open(REPORT)
    doc[2].set_rotation(90)
    flagged = doc.tobytes()
    for layer in (read(flagged, PyMuPDFParser()), read(flagged, PdfiumParser())):
        page = layer.pages[2]
        assert (page.rotation, page.width, page.height) == (90, 595.0, 842.0)
        (span,) = find_quote("412 (34.5%)", layer.text)
        (box,) = make_anchor(layer, span).boxes
        for got, want in zip(
            box.model_dump().values(), expected.model_dump().values(), strict=True
        ):
            assert abs(got - want) < 1.5, layer.recipe.engine

    # Landscape pages with the report drawn sideways and no /Rotate: the reader turns their
    # head, and so does the reading order. Columns and table rows still read in order.
    turned = _sideways_pdf()
    for layer in (read(turned, PyMuPDFParser()), read(turned, PdfiumParser())):
        assert layer.pages[0].rotation == 0
        (span,) = find_quote(COLUMN_BREAK_QUOTE, layer.text)
        assert len(make_anchor(layer, span).boxes) == 3, layer.recipe.engine
        assert find_quote("EPT individuals, n (%) 412 (34.5%) 298 (27.1%)", layer.text)
        (span,) = find_quote("412 (34.5%)", layer.text)
        (box,) = make_anchor(layer, span).boxes
        assert box.x1 - box.x0 < box.y1 - box.y0  # a sideways word is a tall box
        assert text_under(turned, box) == "412 (34.5%)", layer.recipe.engine


def test_part_of_a_sideways_word_is_cut_along_its_reading_direction():
    turned = _sideways_pdf()
    for layer in (read(turned, PyMuPDFParser()), read(turned, PdfiumParser())):
        assert layer.pages[1].frame == 90
        (span,) = find_quote("412 (34.5%)", layer.text)
        word = next(w for w in layer.words if w.start == span.start)
        assert layer.text[word.start : word.end] == "412"
        (box,) = make_anchor(layer, Span(span.start, span.start + 2)).boxes  # "41"
        assert (box.x0, box.x1) == (word.box.x0, word.box.x1)  # the full line height
        third = (word.box.y1 - word.box.y0) * 2 / 3
        assert abs((box.y1 - box.y0) - third) < 0.1  # two of three characters
        assert text_under(turned, box) == "41", layer.recipe.engine


def test_docling_reparse_keeps_table_and_text_anchors(report, report_pdf):
    if not docling_available():
        pytest.skip("the docling extra or its model weights are not installed")
    docling = read(report_pdf, DoclingParser(page_range=(2, 3)))
    assert docling.recipe.engine == "docling" and len(docling.recipe.weights) == 2

    table = next(t for t in docling.tables if t.page == 3)
    header = next(c for c in docling.cells if c.table_id == table.id and c.row == 0 and c.col == 1)
    assert squash(docling.text[header.start : header.end]) == "Site A (n = 120)"
    assert header.col_span == 3  # TableFormer's span, text from PyMuPDF

    for anchor in _anchors(report, [COLUMN_BREAK_QUOTE, "412 (34.5%)", REPEATED]):
        resolution = resolve(anchor, docling)
        assert resolution.status == "exact", anchor.quote.exact
        assert resolution.method_version == RESOLVE_VERSION
        assert resolution.anchor is not None
        old = [(c.row, c.col, c.header_path) for c in anchor.cells]
        new = [(c.row, c.col, c.header_path) for c in resolution.anchor.cells]
        assert new == old


@pytest.mark.parametrize("quote", ["412 (34.5%)", COLUMN_BREAK_QUOTE])
def test_an_anchor_resolves_onto_its_own_layer(report, quote):
    (anchor,) = _anchors(report, [quote])
    resolution = resolve(anchor, report)
    assert (resolution.status, resolution.method, resolution.anchor) == (
        "exact",
        "same_layer",
        anchor,
    )


def _text_layers(old: str, new: str) -> tuple[Layer, Layer]:
    """Two layers of one document whose text differs, laid out identically."""
    return text_layer(old, name="old"), text_layer(new, name="new")


@pytest.mark.parametrize(
    ("new_text", "status"),
    [
        ("Survey: N = 123 ponds were sampled.", "unresolved"),  # 12 became 123
        ("Survey: N = 12.5 ponds were sampled.", "unresolved"),  # 12 became 12.5
        ("Survey: N = 412 ponds were sampled.", "unresolved"),  # 12 became 412
        ("Survey: N = 12 lakes were sampled.", "candidate"),  # same number, new context
        ("Survey: N = -12 ponds were sampled.", "candidate"),  # a sign before it
        ("Survey: N = 12 ponds were sampled.", "exact"),
        ("Survey: N =  12   ponds were\nsampled.", "exact"),  # spacing only
    ],
)
def test_a_changed_number_or_context_is_never_exact(new_text, status):
    old, new = _text_layers("Survey: N = 12 ponds were sampled.", new_text)
    (span,) = find_quote("12", old.text)
    resolution = resolve(make_anchor(old, span), new)
    assert resolution.status == status
    if resolution.anchor is not None:
        assert new.text[resolution.anchor.start : resolution.anchor.end] == "12"


def test_whitespace_between_blocks_never_starves_the_context():
    # The same words, one engine putting each in its own block ("\n\n" between them).
    letters = "A B C D E F G H I J K L M N O P"
    blocks = "Total: 12\n\n" + "\n\n".join(letters.split()) + "\n\nend."
    packed = "Total: 12\n\n" + letters + "\n\nend."
    old, new = _text_layers(blocks, packed)
    (span,) = find_quote("12", old.text)
    assert resolve(make_anchor(old, span), new).status == "exact"


def test_a_quote_across_a_hyphenated_break_reanchors_onto_the_solid_word():
    old, new = _text_layers(
        "Most surveys found no evi-\ndence of decline in spring.",
        "Most surveys found no evidence of decline in spring.",
    )
    (span,) = find_quote("evidence of decline", old.text)
    anchor = make_anchor(old, span)
    assert "-" in anchor.quote.exact  # the anchor keeps the printed, hyphenated form
    resolution = resolve(anchor, new)
    assert resolution.status in {"exact", "candidate"}
    assert resolution.anchor is not None
    assert new.text[resolution.anchor.start : resolution.anchor.end] == "evidence of decline"


def test_a_changed_word_beside_the_quote_is_never_exact():
    old, new = _text_layers("There were 12 live specimens.", "There were 12 dead specimens.")
    (span,) = find_quote("12", old.text)
    assert resolve(make_anchor(old, span), new).status == "candidate"


def test_resolve_refuses_a_layer_of_another_document():
    # Same quote, same geometry, different PDF bytes: a revision is a different document.
    text = "Survey: N = 12 ponds were sampled."
    first = text_layer(text, pdf=b"%PDF-1.7 first")
    revised = text_layer(text, pdf=b"%PDF-1.7 revised")
    (span,) = find_quote("12 ponds", first.text)
    with pytest.raises(DifferentDocument):
        resolve(make_anchor(first, span), revised)
