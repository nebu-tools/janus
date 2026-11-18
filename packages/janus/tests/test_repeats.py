"""The header printed again.

The header printed first in reading order heads the table that is read, ruled or not. Every other
place it is printed ends that table, and leaves the field ambiguous unless a key says what it is:
`continues: none` (another table), `skip:` (a line of the same table), `stop:` (the end of the
field), `continues: header` (the same table on the next page) or `pages:`.

The packing list prints the header again once on each page: page 1 under a printed table by a
ruled one, page 2 twice in one printed table, page 3 under a ruled table by a printed one, and
pages 4 and 5 at the top of each page.
"""

import pytest

from janus_pdf import extract, load_spec
from janus_pdf.document import read
from support import PACKING

HEADER = {"item": "Item", "qty": "Qty"}


@pytest.fixture(scope="module")
def packing():
    return read(PACKING.read_bytes())


def lines(layer, pages, **records):
    spec = {"records": {"header": HEADER, **records}, "columns": {"qty": "integer"}}
    if pages is not None:
        spec["pages"] = pages
    extraction = extract(layer, load_spec({"fields": {"lines": spec}}))
    return extraction.result("lines"), extraction.data["lines"]


def items(data) -> list[str]:
    return [r["item"] for r in data]


def test_the_header_printed_first_is_read_whatever_kind_of_table_it_heads(packing):
    head, _ = lines(packing, 1, continues="none")
    assert head.method == "records:layout" and head.status == "extracted"
    head, _ = lines(packing, 3, continues="none")
    assert head.method == "records" and head.status == "extracted"


@pytest.mark.parametrize("page", [1, 3])
def test_a_table_of_the_other_kind_under_the_same_header_is_ambiguous(packing, page):
    head, data = lines(packing, page)
    assert head.status == "ambiguous" and data is None
    assert f"printed again on page {page}" in head.message
    assert "`continues: none`" in head.message
    assert "no key reads a ruled table and a table without rules as one" in head.message


def test_continues_none_reads_only_the_first_table(packing):
    for page, first in ((1, ["Apple", "Pear"]), (2, ["Fig"]), (3, ["Lime"]), ("4-5", ["Nut"])):
        head, data = lines(packing, page, continues="none")
        assert head.status == "extracted" and items(data) == first, page
        assert "`continues: none`: the header printed again on page" in head.message


def test_the_same_header_twice_on_a_page_is_ambiguous(packing):
    head, data = lines(packing, 2)
    assert head.status == "ambiguous" and data is None
    assert "printed again on page 2" in head.message
    assert "`continues: none`" in head.message and "`skip: [Item]`" in head.message


def test_skip_reads_the_header_printed_again_as_a_line_of_the_same_table(packing):
    head, data = lines(packing, 2, skip=["Item"])
    assert head.status == "extracted" and items(data) == ["Fig", "Kiwi"]
    assert "left out by `skip:`: 'Item Qty' on page 2" in head.message


def test_a_header_on_a_later_page_is_ambiguous_until_declared(packing):
    head, data = lines(packing, "4-5")
    assert head.status == "ambiguous" and data is None
    assert "printed again on page 5" in head.message
    assert "`continues: header`" in head.message and "`pages: 4`" in head.message
    head, data = lines(packing, "4-5", continues="header")
    assert head.status == "extracted" and items(data) == ["Nut", "Oat"]
    assert "left out the header printed again on page 5" in head.message


def test_a_flowing_table_names_stop_for_a_header_printed_again_mid_page(packing):
    head, _ = lines(packing, 2, continues="header")
    assert head.status == "ambiguous" and "`stop: [Item]`" in head.message
    head, data = lines(packing, 2, continues="header", stop=["Item"])
    assert head.status == "extracted" and items(data) == ["Fig"]


def test_the_whole_document_is_ambiguous_at_the_first_header_printed_again(packing):
    head, data = lines(packing, None)
    assert head.status == "ambiguous" and data is None
    assert "printed again on page 1" in head.message
