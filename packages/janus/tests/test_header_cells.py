"""Rows that print the header's words without being the header.

A row is the header when each declared header is the whole text of a cell of its own, and a row
after the first is the header printed again only with each header in the column the first set.
The header-cells fixture prints, under the header Item / Qty: the header's words inside a longer
cell, without rules (page 1) and ruled (page 2); the header's texts in swapped columns, without
rules (page 3) and ruled (page 4); a row labelled "Qty" beside a number, a row labelled "Item"
and a total row (page 5); and a header printed over two lines (page 6).
"""

import pytest

from janus_pdf import extract, load_spec
from janus_pdf.document import read
from support import CELLS, drawn

HEADER = {"item": "Item", "qty": "Qty"}


@pytest.fixture(scope="module")
def cells():
    return read(CELLS.read_bytes())


def lines(layer, pages, header=HEADER, typed=True, **records):
    spec: dict = {"pages": pages, "records": {"header": header, **records}}
    if typed:
        spec["columns"] = {"qty": "integer"}
    extraction = extract(layer, load_spec({"fields": {"lines": spec}}))
    return extraction.result("lines"), extraction.data["lines"]


def items(data) -> list[str]:
    return [r["item"] for r in data]


BODY = ["Apple", "Item Qty adapter", "Pear", "Total"]


@pytest.mark.parametrize(("page", "method"), [(1, "records:layout"), (2, "records")])
@pytest.mark.parametrize("form", [None, "none", "header", "rows"])
def test_the_header_words_inside_a_longer_cell_are_a_record(cells, page, method, form):
    head, data = lines(cells, page, **({"continues": form} if form else {}))
    assert head.status == "extracted" and head.method == method, head.message
    assert items(data) == BODY and data[1]["qty"] == 2
    assert "printed again" not in head.message


@pytest.mark.parametrize("page", [1, 2])
def test_stop_and_skip_still_take_the_total_row(cells, page):
    head, data = lines(cells, page, stop=["Total"])
    assert head.status == "extracted" and items(data) == BODY[:3]
    head, data = lines(cells, page, skip=["Total"])
    assert head.status == "extracted" and items(data) == BODY[:3]
    assert f"left out by `skip:`: 'Total 6' on page {page}" in head.message


@pytest.mark.parametrize("page", [3, 4])
def test_the_header_texts_in_swapped_columns_are_a_record(cells, page):
    head, data = lines(cells, page, typed=False)
    assert head.status == "extracted", head.message
    assert data[1] == {"item": "Qty", "qty": "Item"}
    head, data = lines(cells, page)
    assert head.status == "invalid" and data is None
    assert f"qty 'Item' in the row 'Qty Item' on page {page}" in head.message


def test_a_row_labelled_with_a_header_text_beside_a_number_is_a_record(cells):
    head, data = lines(cells, 5)
    assert head.status == "extracted", head.message
    assert data == [
        {"item": "Apple", "qty": 1},
        {"item": "Qty", "qty": 3},
        {"item": "Item", "qty": 2},
        {"item": "Total", "qty": 6},
    ]


def test_a_header_over_two_lines_is_two_rows(cells):
    head, data = lines(cells, 6, header={"item": "Item description", "qty": "Qty"})
    assert head.status == "missing" and data is None
    assert "in a cell of its own: Item description, Qty" in head.message
    head, data = lines(cells, 6)
    assert head.status == "ambiguous" and "the line 'description' on page 6" in head.message
    head, data = lines(cells, 6, skip=["description"])
    assert head.status == "extracted" and items(data) == ["Apple", "Pear"]


def test_the_header_printed_again_in_its_columns_still_matches(cells):
    """The fixture's pages each open with the header in the same columns, so over two pages the
    second is the header printed again, of the same kind or the other."""
    for pages in ("1-2", "3-4"):
        head, data = lines(cells, pages, typed=False)
        assert head.status == "ambiguous" and data is None
        assert f"printed again on page {pages[-1]}" in head.message


def test_a_page_opening_with_the_header_texts_in_swapped_columns_does_not_continue_it():
    """Under `continues: header` the header at the top of the next page is tested by the same
    rule, columns included."""
    layer = drawn(
        [(60, 100, "Item"), (300, 100, "Qty"), (60, 125, "Apple"), (300, 125, "1")],
        [(60, 100, "Qty"), (300, 100, "Item"), (60, 125, "Pear"), (300, 125, "2")],
    )
    head, data = lines(layer, "1-2", continues="header")
    assert head.status == "extracted" and items(data) == ["Apple"], head.message
    assert head.message == "1 row under the header on page 1"
    head, data = lines(layer, "1-2", typed=False)
    assert head.status == "incomplete" and "page 2" in head.message
