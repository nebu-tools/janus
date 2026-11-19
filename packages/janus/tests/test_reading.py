"""Reading the generated survey report into layers, and anchoring quotes and table cells in it."""

import os
import re

import pymupdf
import pytest

from janus_pdf.document import (
    EmptyPdf,
    EncryptedPdf,
    Layer,
    NotAPdf,
    OcrMyPdfParser,
    OcrUnavailable,
    PdfiumParser,
    PyMuPDFParser,
    UnreadablePdf,
    find_quote,
    layer_of,
    make_anchor,
    ocr_available,
    read,
    render_png,
    triage,
)
from support import (
    COLUMN_BREAK_QUOTE,
    GUTTER,
    REPORT,
    SOFT_HYPHEN_QUOTE,
    ink,
    squash,
    text_under,
)


def _cells(layer: Layer, table_id: str):
    return {(c.row, c.col): c for c in layer.cells if c.table_id == table_id}


def _text(layer: Layer, item) -> str:
    return squash(layer.text[item.start : item.end])


def test_quote_across_a_column_break_gets_one_box_per_line_in_both_columns(report, report_pdf):
    (span,) = find_quote(COLUMN_BREAK_QUOTE, report.text)
    anchor = make_anchor(report, span)

    # Two lines at the foot of the left column ("consis-" is hyphenated), one at the top of the right.
    assert [b.page for b in anchor.boxes] == [2, 2, 2]
    first, second, third = anchor.boxes
    assert first.x1 < GUTTER and second.x1 < GUTTER and third.x0 > GUTTER
    assert first.y0 < second.y0 and third.y0 < first.y0
    # A different engine reads exactly the quoted words inside the boxes, line by line.
    assert text_under(report_pdf, first) == "Abundance estimates were directionally consis-"
    assert text_under(report_pdf, second) == "tent across both sites and agreed with the"
    assert text_under(report_pdf, third) == "counts from the earlier survey of the same"
    assert anchor.quote.prefix.endswith("below 5% in every batch.\n")
    assert anchor.quote.suffix.startswith("\nstreams in the winter")
    assert anchor.cells == ()


def test_quote_across_a_soft_hyphenated_line_break(report, report_pdf):
    # The PDF breaks "resid-ing" with a soft hyphen; the quote has the whole word.
    (span,) = find_quote(SOFT_HYPHEN_QUOTE, report.text)
    first, second = make_anchor(report, span).boxes
    assert first.page == second.page == 2
    assert first.y0 + 8 < second.y0 < first.y1 + 4  # the next line down
    assert second.x0 < first.x0  # which starts at the column margin
    assert text_under(report_pdf, first) == "under stones, resid-"
    assert text_under(report_pdf, second) == "ing in the fastest"


def test_running_heads_and_footers_open_and_close_every_page(report):
    for page in report.pages:
        text = report.text[page.start : page.end]
        assert text.startswith("Northfield Ecology Group | Stream Invertebrate Survey 2026")
        assert text.rstrip().endswith(f"Page {page.number} of 4")


@pytest.mark.parametrize("engine", ["pymupdf", "pdfium"])
def test_lines_carry_font_size_and_weight_in_both_engines(engine, report, report_pdfium):
    layer = report if engine == "pymupdf" else report_pdfium
    lines = {_text(layer, ln): ln for ln in layer.lines}
    title = lines["Stream Invertebrate Survey 2026"]
    assert (title.size, title.bold) == (18.0, True)
    heading = lines["2 Methods"]
    assert (heading.size, heading.bold) == (12.0, True)
    assert lines["2.1 Sampling"].bold and lines["3.1 Sampling"].bold
    body = next(ln for text, ln in lines.items() if text.startswith("Three-minute kick samples"))
    assert (body.size, body.bold) == (9.5, False)


def test_table_cell_value_anchors_to_its_cell_under_nested_headers(report, report_pdf):
    table = next(t for t in report.tables if t.page == 3)
    cells = _cells(report, table.id)

    # "Measure" spans both header rows; "Site A" and "Site B" each span three habitats.
    assert (_text(report, cells[0, 0]), cells[0, 0].row_span) == ("Measure", 2)
    assert (_text(report, cells[0, 1]), cells[0, 1].col_span) == ("Site A (n = 120)", 3)
    assert (_text(report, cells[0, 4]), cells[0, 4].col_span) == ("Site B (n = 120)", 3)
    assert [_text(report, cells[1, c]) for c in range(1, 7)] == ["Riffle", "Pool", "Run"] * 2

    (span,) = find_quote("412 (34.5%)", report.text)  # EPT individuals, Site A, riffles
    anchor = make_anchor(report, span)
    (ref,) = anchor.cells
    assert (ref.table_id, ref.col) == (table.id, 1)
    assert ref.header_path == ("Site A (n = 120)", "Riffle")
    assert _text(report, cells[ref.row, 0]) == "EPT individuals, n (%)"
    assert _text(report, cells[ref.row, 4]) == "260 (22.4%)"  # the same row, Site B
    (box,) = anchor.boxes
    cell_box = cells[ref.row, ref.col].box
    assert cell_box.x0 <= box.x0 and box.x1 <= cell_box.x1
    assert cell_box.y0 <= box.y0 and box.y1 <= cell_box.y1
    assert text_under(report_pdf, box) == "412 (34.5%)"


def test_row_spanning_header_cells_and_two_tables_on_a_page(report):
    on_page_4 = [t for t in report.tables if t.page == 4]
    assert len(on_page_4) == 2  # Table 2 and Table 3
    table3 = on_page_4[1]
    cells = _cells(report, table3.id)
    measure = cells[0, 0]
    assert _text(report, measure) == "Measure"
    assert measure.row_span == 2 and measure.role == "header"

    (span,) = find_quote("0.5 (0.1, 0.9)", report.text)  # body length, riffles, difference
    (ref,) = make_anchor(report, span).cells
    assert ref.table_id == table3.id
    assert ref.header_path == ("Difference between sites", "Estimate (95% CI)")
    assert _text(report, cells[ref.row, 1]) == "Riffle"
    assert _text(report, cells[ref.row, 5]) == "P = 0.03"


def test_a_ruled_table_whose_first_row_is_a_title(report):
    table2 = next(t for t in report.tables if t.page == 4)
    cells = _cells(report, table2.id)
    assert _text(report, cells[0, 0]) == "Water chemistry, February 2026"
    assert [_text(report, cells[1, c]) for c in range(5)] == [
        "Site",
        "Visit date",
        "pH",
        "EC, µS/cm",
        "Nitrate, mg/L",
    ]
    assert [_text(report, cells[4, c]) for c in range(5)] == [
        "Site B",
        "03/02/2026",
        "7.8",
        "604",
        "7.6",
    ]
    # The title spans the table and heads no column; the row under it is the header.
    assert (cells[0, 0].role, cells[0, 0].col_span) == ("title", 5)
    assert [cells[1, c].role for c in range(5)] == ["header"] * 5
    assert cells[4, 3].header_path == ("EC, µS/cm",)
    assert cells[1, 3].header_path == ()


def test_a_row_label_wider_than_its_column_keeps_to_its_cell(report):
    """The longest row label of Table 1 reaches past where the next column's values start in
    other rows; it stays one cell, and the value beside it is the next cell."""
    table1 = next(t for t in report.tables if t.page == 3)
    cells = _cells(report, table1.id)
    label = next(c for c in cells.values() if _text(report, c).startswith("Taxa per sample"))
    assert (_text(report, label), label.col, label.col_span) == ("Taxa per sample, mean (SD)", 0, 1)
    value = cells[label.row, 1]
    assert _text(report, value) == "14.2 (3.1)"
    assert value.header_path == ("Site A (n = 120)", "Riffle")


def test_a_borderless_table_reads_row_by_row(report):
    page = report.pages[3]
    text = squash(report.text[page.start : page.end])
    assert "Site Date Start Samples Site A 3 February 2026 09:40 30 Site B 3 February 2026" in text
    assert not any(t.box.y0 > 400 for t in report.tables if t.page == 4)  # no rules, no table


def test_repeated_section_headings_are_separate_lines(report):
    sampling = [ln for ln in report.lines if _text(report, ln).endswith(" Sampling")]
    assert [(_text(report, ln), ln.box.page) for ln in sampling] == [
        ("2.1 Sampling", 1),
        ("3.1 Sampling", 2),
    ]


def test_render_puts_word_boxes_on_printed_ink(report, report_pdf):
    scale = 1.5
    png = render_png(report_pdf, 2, scale)
    pixmap = pymupdf.Pixmap(png)
    assert abs(pixmap.width - 595 * scale) <= 1 and abs(pixmap.height - 842 * scale) <= 1
    (span,) = find_quote(COLUMN_BREAK_QUOTE, report.text)
    boxes = make_anchor(report, span).boxes
    for box in boxes:
        assert ink(png, box, scale) > 0.05
    # The gutter beside the quote's lines is blank paper.
    gutter = boxes[0].model_copy(update={"x0": GUTTER - 3, "x1": GUTTER + 3, "y1": boxes[1].y1})
    assert ink(png, gutter, scale) == 0.0
    with pytest.raises(IndexError):
        render_png(report_pdf, 5, scale)
    with pytest.raises(ValueError, match="scale"):
        render_png(report_pdf, 1, 10.0)


def _broken_cmap(pdf: bytes) -> bytes:
    """The PDF with every ToUnicode entry mapped to a private-use character."""
    doc = pymupdf.open("pdf", pdf)
    for xref in range(1, doc.xref_length()):
        kind, value = doc.xref_get_key(xref, "ToUnicode")
        if kind == "xref":
            stream = int(value.split()[0])
            cmap = doc.xref_stream(stream).decode("latin-1")
            cmap = re.sub(
                r"(beginbf(?:char|range).*?endbf(?:char|range))",
                lambda m: re.sub(r"<[0-9A-Fa-f]+>(\s*)$", r"<E000>\1", m.group(1), flags=re.M),
                cmap,
                flags=re.S,
            )
            doc.update_stream(stream, cmap.encode("latin-1"))
    return doc.tobytes()


def _mixed_pdf() -> bytes:
    """Page 1 a born-digital page, page 2 with a ToUnicode map that maps every glyph to a
    private-use character, page 3 an image of a page with no text layer."""
    report = pymupdf.open(REPORT)
    broken = pymupdf.open()
    broken.insert_pdf(report, from_page=1, to_page=1)
    out = pymupdf.open()
    out.insert_pdf(report, from_page=0, to_page=0)
    out.insert_pdf(pymupdf.open("pdf", _broken_cmap(broken.tobytes())))
    scan = out.new_page(width=report[2].rect.width, height=report[2].rect.height)
    scan.insert_image(scan.rect, pixmap=report[2].get_pixmap(dpi=100))
    return out.tobytes()


def test_triage_marks_scanned_and_broken_pages_and_the_layer_keeps_it():
    pdf = _mixed_pdf()
    pages = triage(pdf)
    assert [p.kind for p in pages] == ["text", "broken_encoding", "ocr"]
    assert any(r.startswith("pymupdf_suspicious_chars") for r in pages[1].reasons)

    layer = read(pdf)
    assert [p.triage.kind if p.triage else None for p in layer.pages] == [
        "text",
        "broken_encoding",
        "ocr",
    ]
    # The scan has no words, and the broken page's text cannot ground a quote.
    assert layer.pages[2].start == layer.pages[2].end
    assert find_quote("Abundance", layer.text[layer.pages[1].start : layer.pages[1].end]) == ()


def test_ocr_gives_the_scanned_page_a_text_layer():
    if not ocr_available():
        with pytest.raises(OcrUnavailable):
            OcrMyPdfParser()
        pytest.skip("ocrmypdf and tesseract are not installed; the OCR path refuses to start")
    layer = read(_mixed_pdf(), OcrMyPdfParser())
    scanned = layer.text[layer.pages[2].start : layer.pages[2].end]
    assert find_quote("Invertebrates per sample", scanned)


def test_reading_is_deterministic_per_recipe_and_layers_are_immutable(report, report_pdfium):
    again = read(REPORT)
    assert again == report and again.id == report.id
    assert again.document_hash == report_pdfium.document_hash
    assert report_pdfium.recipe.engine == "pypdfium2"
    assert report_pdfium.id != report.id
    with pytest.raises(ValueError, match="frozen"):
        report.text = "changed"  # ty: ignore[invalid-assignment]


def test_a_layer_is_identified_by_document_recipe_and_output(report_pdf):
    """Two files that read the same, or one file read the same by two recipes, are not one layer."""
    doc = pymupdf.open("pdf", report_pdf)
    doc.set_metadata({"title": "Another title"})
    retitled = doc.tobytes()
    same_words = read(retitled)
    first = read(report_pdf)
    assert same_words.text == first.text and same_words.words == first.words
    assert same_words.document_hash != first.document_hash
    assert same_words.id != first.id

    parser = PyMuPDFParser()
    raw = parser.parse(report_pdf)
    other = parser.recipe.model_copy(update={"engine_version": "0"})
    assert layer_of(report_pdf, raw, other).id != layer_of(report_pdf, raw, parser.recipe).id
    assert layer_of(report_pdf, raw, parser.recipe).id == first.id


def test_recipes_name_what_ran():
    recipe = dict(PyMuPDFParser().recipe.settings)
    assert recipe["assembly"] == "janus.layout.v4"
    assert recipe["tables"] == "janus.tables.v2"
    assert recipe["triage"].endswith("pymupdf.v1")
    assert dict(PdfiumParser().recipe.settings)["fonts"] == "pdfium.v1"


def test_bytes_that_are_not_a_pdf_are_refused(tmp_path):
    with pytest.raises(NotAPdf):
        read(b"<html>not a pdf</html>")
    path = tmp_path / "note.txt"
    path.write_text("hello")
    with pytest.raises(NotAPdf):
        read(path)


def _zero_page_pdf() -> bytes:
    """A well-formed PDF whose page tree is empty (PyMuPDF refuses to save one)."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [] /Count 0 >>"]
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def _encrypted(pdf: bytes, user_password: str) -> bytes:
    doc = pymupdf.open("pdf", pdf)
    return doc.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw=user_password
    )


@pytest.mark.parametrize("parser", [PyMuPDFParser(), PdfiumParser()], ids=["pymupdf", "pdfium"])
def test_files_that_cannot_be_read_completely_are_refused_by_kind(report_pdf, parser):
    with pytest.raises(EmptyPdf):
        read(_zero_page_pdf(), parser)
    with pytest.raises(EncryptedPdf):
        read(_encrypted(report_pdf, "secret"), parser)
    with pytest.raises(NotAPdf):
        read(report_pdf[: len(report_pdf) // 3].replace(b"obj", b"jbo"), parser)
    for error in (EmptyPdf, EncryptedPdf, NotAPdf):
        assert issubclass(error, UnreadablePdf)
    # Encrypted against editing only: it opens without a password and reads like the original.
    restricted = read(_encrypted(report_pdf, ""), parser)
    assert squash(restricted.text) == squash(read(report_pdf, parser).text)


def test_a_failed_read_closes_every_document_and_page(report_pdf, monkeypatch):
    """A parser that fails on page 3 still closes what it opened."""
    from janus_pdf.document import engines

    opened: list = []
    real_open = pymupdf.open

    def tracked_open(*args, **kwargs):
        doc = real_open(*args, **kwargs)
        opened.append(doc)
        return doc

    def fail_on_third(page, *args, **kwargs):
        if page.number == 2:
            raise RuntimeError("broken page")
        return real_page_input(page, *args, **kwargs)

    real_page_input = engines.pymupdf_page_input
    monkeypatch.setattr(engines.pymupdf, "open", tracked_open)
    monkeypatch.setattr(engines, "pymupdf_page_input", fail_on_third)
    with pytest.raises(RuntimeError, match="broken page"):
        PyMuPDFParser().parse(report_pdf)
    assert opened and all(doc.is_closed for doc in opened)

    made: list = []  # every PDFium document, page and text page the parser opened
    real_doc, real_chars = engines.pypdfium2.PdfDocument, engines._chars_of

    class TrackedDocument(real_doc):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

        def __getitem__(self, i):
            page = super().__getitem__(i)
            made.append(page)
            return page

    def chars_failing_on_third(textpage, left, top):
        made.append(textpage)
        if sum(isinstance(m, engines.pypdfium2.PdfPage) for m in made) == 3:
            raise RuntimeError("broken page")
        return real_chars(textpage, left, top)

    monkeypatch.setattr(engines.pypdfium2, "PdfDocument", TrackedDocument)
    monkeypatch.setattr(engines, "_chars_of", chars_failing_on_third)
    with pytest.raises(RuntimeError, match="broken page"):
        PdfiumParser().parse(report_pdf)
    assert len(made) == 7  # the document, three pages and their text pages
    assert all(m.raw is None for m in made)


def test_a_read_with_a_cache_goes_on_from_the_pages_already_read(tmp_path, report_pdf, monkeypatch):
    from janus_pdf.document import engines

    plain = read(report_pdf)
    real_page_input = engines.pymupdf_page_input
    seen: list[int] = []

    def stop_at_third(page, *args, **kwargs):
        if page.number == 2:
            raise KeyboardInterrupt
        seen.append(page.number)
        return real_page_input(page, *args, **kwargs)

    monkeypatch.setattr(engines, "pymupdf_page_input", stop_at_third)
    with pytest.raises(KeyboardInterrupt):
        read(report_pdf, PyMuPDFParser(cache=tmp_path))
    assert seen == [0, 1]
    assert len(list(tmp_path.glob("*.json"))) == 2  # one file for each page read

    def count(page, *args, **kwargs):
        seen.append(page.number)
        return real_page_input(page, *args, **kwargs)

    monkeypatch.setattr(engines, "pymupdf_page_input", count)
    resumed = read(report_pdf, PyMuPDFParser(cache=tmp_path))
    assert seen == [0, 1, 2, 3]  # the two pages read before are not read again
    assert resumed == plain  # the same layer, with the same ID, as a read without a cache
    assert len(list(tmp_path.glob("*.json"))) == len(plain.pages)

    monkeypatch.setattr(engines, "pymupdf_page_input", None)  # a third read parses no page
    assert read(report_pdf, PyMuPDFParser(cache=tmp_path)) == plain


def _counting(monkeypatch) -> list[int]:
    """The numbers of the pages PyMuPDF parses from now on, from 0."""
    from janus_pdf.document import engines

    real_page_input = engines.pymupdf_page_input
    seen: list[int] = []

    def count(page, *args, **kwargs):
        seen.append(page.number)
        return real_page_input(page, *args, **kwargs)

    monkeypatch.setattr(engines, "pymupdf_page_input", count)
    return seen


def test_a_cache_file_that_is_not_a_whole_page_is_read_again(tmp_path, report_pdf, monkeypatch):
    plain = read(report_pdf)
    read(report_pdf, PyMuPDFParser(cache=tmp_path))
    first, second = sorted(tmp_path.glob("*.json"))[:2]
    whole = first.read_bytes()
    first.write_bytes(whole[:40])  # cut off
    second.write_bytes(whole)  # a whole page, but page 1 under the name of page 2
    seen = _counting(monkeypatch)
    assert read(report_pdf, PyMuPDFParser(cache=tmp_path)) == plain
    assert seen == [0, 1]
    seen.clear()
    assert read(report_pdf, PyMuPDFParser(cache=tmp_path)) == plain
    assert seen == []  # both were written again, whole


def test_a_cache_entry_is_never_taken_for_other_bytes(tmp_path, report_pdf, monkeypatch):
    from support import INVOICE

    plain = read(report_pdf)
    read(INVOICE, PyMuPDFParser(cache=tmp_path))
    (invoice_page,) = tmp_path.glob("*.json")
    seen = _counting(monkeypatch)
    assert read(report_pdf, PyMuPDFParser(cache=tmp_path)) == plain
    assert seen == [0, 1, 2, 3]  # every page parsed, none taken from the cache
    assert invoice_page.exists()  # and nothing deleted that this read did not write


def test_a_cache_entry_is_never_taken_for_another_recipe(tmp_path, report_pdf, monkeypatch):
    read(report_pdf, PyMuPDFParser(cache=tmp_path))
    other = PyMuPDFParser(cache=tmp_path)
    other.recipe = other.recipe.model_copy(
        update={"settings": (*other.recipe.settings, ("assembly.extra", "1"))}
    )
    seen = _counting(monkeypatch)
    read(report_pdf, other)
    assert seen == [0, 1, 2, 3]
    assert len(list(tmp_path.glob("*.json"))) == 8  # both recipes' pages, side by side


def test_the_cache_key_covers_the_bytes_and_the_recipe(report_pdf):
    from janus_pdf.document.engines import page_cache_key

    recipe = PyMuPDFParser().recipe
    key = page_cache_key(report_pdf, recipe)
    assert re.fullmatch(r"[0-9a-f]{64}", key)
    assert page_cache_key(report_pdf, recipe) == key
    assert page_cache_key(report_pdf + b" ", recipe) != key
    changed = recipe.model_copy(update={"engine_version": recipe.engine_version + "x"})
    assert page_cache_key(report_pdf, changed) != key


def test_two_writers_of_the_same_page_leave_one_whole_file(tmp_path, report_pdf, monkeypatch):
    from janus_pdf.document import engines

    store = engines._PageStore(tmp_path, report_pdf, PyMuPDFParser().recipe)
    with pymupdf.open(stream=report_pdf) as doc:
        page = engines.pymupdf_page_input(doc[0])
    real_replace = os.replace
    nested = []

    def replace(source, target):
        # The second writer runs to the end between the first writer's write and its move.
        if not nested:
            nested.append(source)
            store.put(page)
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", replace)
    store.put(page)
    assert [p.name for p in tmp_path.iterdir()] == [f"{store.key}-000001.json"]
    assert store.get(1) == page


_KILLED_WRITER = """
import os, signal, sys
from pathlib import Path
import pymupdf
from janus_pdf.document import engines

directory, pdf = Path(sys.argv[1]), Path(sys.argv[2]).read_bytes()
fdopen = os.fdopen

class Dies:
    def __init__(self, out):
        self.out = out
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        self.out.close()
    def write(self, data):
        self.out.write(data[: len(data) // 2])
        self.out.flush()
        os.kill(os.getpid(), signal.SIGKILL)

engines.os.fdopen = lambda fd, mode: Dies(fdopen(fd, mode))
store = engines._PageStore(directory, pdf, engines.PyMuPDFParser().recipe)
with pymupdf.open(stream=pdf) as doc:
    store.put(engines.pymupdf_page_input(doc[0]))
"""


def test_a_writer_killed_in_the_middle_of_a_write_leaves_a_part_the_next_writers_remove(
    tmp_path, report_pdf
):
    import signal
    import subprocess
    import sys
    import time

    from janus_pdf.document import engines

    cache = tmp_path / "pages"
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(report_pdf)
    killed = subprocess.run([sys.executable, "-c", _KILLED_WRITER, str(cache), str(pdf)])
    assert killed.returncode == -signal.SIGKILL

    recipe = PyMuPDFParser().recipe
    store = engines._PageStore(cache, report_pdf, recipe)
    (left,) = cache.iterdir()
    assert left.name.startswith(f".{store.key}-") and left.suffix == ".part"
    assert left.stat().st_size > 0  # half a page
    assert store.get(1) is None  # and it is never taken for a page

    # The same page is written again at once. The part may belong to a writer still at work.
    whole = read(report_pdf, PyMuPDFParser(cache=tmp_path / "whole"))
    page = engines._PageStore(tmp_path / "whole", report_pdf, recipe).get(1)
    assert page is not None
    store.put(page)
    assert store.get(1) == page
    assert left.exists()

    # Ten minutes on, the next writer of this key removes it. Parts of another key, a younger
    # part of this key and every other file stay.
    old = time.time() - engines._PageStore.STALE_PART - 5
    os.utime(left, (old, old))
    young = cache / f".{store.key}-young.part"
    other = cache / f".{'0' * 64}-other.part"
    note = cache / "note.txt"
    for path in (young, other, note):
        path.write_bytes(b"x")
    for path in (other, note):
        os.utime(path, (old, old))
    engines._PageStore(cache, report_pdf, recipe).put(page)
    assert sorted(p.name for p in cache.iterdir()) == sorted(
        [f"{store.key}-000001.json", young.name, other.name, note.name]
    )
    assert read(report_pdf, PyMuPDFParser(cache=cache)) == whole


def test_page_count_refuses_what_read_refuses(report_pdf):
    from janus_pdf import page_count
    from support import REPORT

    assert page_count(report_pdf) == page_count(REPORT) == 4
    with pytest.raises(NotAPdf):
        page_count(b"plain text")
    doc = pymupdf.open(stream=report_pdf, filetype="pdf")
    locked = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    with pytest.raises(EncryptedPdf):
        page_count(locked)
