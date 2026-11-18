"""The locators on small drawn pages, one case each: what is read, and what is refused."""

from collections.abc import Sequence

import pytest

from janus_pdf import Proposal, SpecError, compare, extract, load_spec
from janus_pdf.document import read
from support import LEDGER, ORDER, REPORT, drawn, text_layer


def run(layer, body, proposer=None):
    return extract(layer, load_spec({"fields": {"x": body}}), proposer)


def one(layer, body, proposer=None):
    return run(layer, body, proposer).result("x")


# --- negatives ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("printed", "value"),
    [
        ("Amount: -123", "-123"),
        ("Amount -123", "-123"),
        ("Amount: \u2212123", "-123"),  # the minus sign
        ("Amount: (123)", "-123"),
        ("Amount: ( 123.50 )", "-123.50"),
        ("Amount: +5", "5"),
        ("Amount: - 7", "-7"),
        ("Amount - 8", "8"),  # a dash with a space after it separates the label
        ("Amount \u2013 9", "9"),
    ],
)
def test_label_keeps_the_sign_and_drops_only_its_separator(printed, value):
    r = one(text_layer(printed), {"label": "Amount", "type": "decimal"})
    assert (r.status, r.value) == ("extracted", value)


def test_parentheses_read_as_negative_with_a_note():
    r = one(drawn([(50, 50, "Change: (12)")]), {"label": "Change", "type": "integer"})
    assert r.value == -12 and "parentheses" in r.message


def test_cells_and_regions_keep_a_leading_dash():
    layer = drawn([(50, 50, "-12")])
    r = one(layer, {"region": {"page": 1, "box": [40, 30, 150, 60]}, "type": "integer"})
    assert r.value == -12


def test_money_in_parentheses_is_negative():
    r = one(drawn([(50, 50, "Credit: (\u00a340.00)")]), {"label": "Credit", "type": "money GBP"})
    assert r.value == {"amount": "-40.00", "currency": "GBP"}


# --- region -------------------------------------------------------------------------------------


def test_region_takes_exactly_the_words_inside_in_reading_order():
    layer = drawn([(50, 50, "LEFT"), (300, 50, "OUTSIDE"), (50, 80, "BOTTOM")])
    r = one(layer, {"region": {"page": 1, "box": [40, 30, 150, 100]}})
    assert (r.status, r.value) == ("extracted", "LEFT BOTTOM")
    assert [a.quote.exact for a in r.anchors] == ["LEFT", "BOTTOM"]
    assert all(a.boxes for a in r.anchors)


def test_region_takes_a_straddling_word_by_its_centre():
    # "Straddling" starts inside the box and has its centre outside it.
    layer = drawn([(50, 50, "In"), (130, 50, "Straddling")])
    r = one(layer, {"region": {"page": 1, "box": [40, 30, 150, 60]}})
    assert r.value == "In"
    r = one(layer, {"region": {"page": 1, "box": [40, 30, 200, 60]}})
    assert r.value == "In Straddling"


def test_region_at_the_page_edge():
    layer = drawn([(2, 838, "Corner"), (300, 400, "Middle")])
    r = one(layer, {"region": {"page": 1, "box": [0, 800, 600, 900]}})
    assert r.value == "Corner"
    r = one(layer, {"region": {"page": 1, "box": [-50, -50, 0, 0]}})
    assert r.status == "missing" and "no words inside the box" in r.message


def test_region_on_a_rotated_page_is_in_displayed_coordinates():
    layer = drawn([(100, 100, "Turned")], rotation=90)
    (word,) = layer.words
    box = word.box
    assert box.x0 > 595 / 2  # turned a quarter clockwise, the top-left text is now top-right
    r = one(layer, {"region": {"page": 1, "box": [box.x0 - 2, box.y0 - 2, box.x1 + 2, box.y1 + 2]}})
    assert r.value == "Turned"
    r = one(layer, {"region": {"page": 1, "box": [90, 80, 160, 110]}})
    assert r.status == "missing"


# --- typed equality -----------------------------------------------------------------------------


def test_text_printed_001_and_1_is_ambiguous():
    r = one(drawn([(50, 50, "Code: 001"), (50, 90, "Code: 1")]), {"label": "Code"})
    assert r.status == "ambiguous" and "'001'" in r.message and "'1'" in r.message


def test_numbers_printed_two_ways_are_the_same_number():
    layer = drawn([(50, 50, "Code: 001"), (50, 90, "Code: 1")])
    r = one(layer, {"label": "Code", "type": "integer"})
    assert (r.status, r.value) == ("extracted", 1)


class Proposer:
    name = "test"

    def __init__(self, value, quote, **kw):
        self.proposal = Proposal(value, quote, **kw)

    def propose(self, *_):
        return self.proposal


def test_a_text_proposal_must_be_the_printed_text():
    layer = drawn([(50, 50, "001")])
    r = one(layer, {"label": "Missing"}, Proposer("1", "001"))
    assert r.status == "unconfirmed" and "'001', not '1'" in r.message
    r = one(layer, {"label": "Missing"}, Proposer("001", "001"))
    assert (r.status, r.value) == ("extracted", "001")
    r = one(layer, {"label": "Missing", "type": "integer"}, Proposer(1, "001"))
    assert (r.status, r.value) == ("extracted", 1)


def test_compare_does_not_match_text_with_a_number():
    layer = drawn([(50, 50, "001")])
    ex = run(layer, {"region": {"page": 1, "box": [0, 0, 500, 500]}})
    (check,) = compare(ex, {"x": 1})
    assert check.status == "mismatch"
    ex = run(layer, {"region": {"page": 1, "box": [0, 0, 500, 500]}, "type": "integer"})
    (check,) = compare(ex, {"x": 1})
    assert check.status == "match"


# --- pages --------------------------------------------------------------------------------------

TWO_PAGES = (
    [(50, 50, "Description"), (300, 50, "Qty"), (50, 80, "Widget"), (300, 80, "1")],
    [(50, 50, "Description"), (300, 50, "Qty"), (50, 80, "Gadget"), (300, 80, "2")],
)
RECORDS = {"records": {"header": {"description": "Description", "qty": "Qty"}}}


def test_a_region_off_the_fields_pages_is_a_spec_error():
    with pytest.raises(SpecError, match=r"region\.page 2 is not on pages 1"):
        load_spec({"fields": {"x": {"region": {"page": 2, "box": [0, 0, 9, 9]}, "pages": 1}}})
    with pytest.raises(SpecError, match=r"cell\.table p3t0 is not on pages 1-2"):
        load_spec(
            {"fields": {"x": {"cell": {"table": "p3t0", "row": 0, "column": 0}, "pages": "1-2"}}}
        )


def test_records_read_only_the_fields_pages():
    layer = drawn(*TWO_PAGES)
    r = run(layer, {**RECORDS, "pages": 2})
    assert r.data["x"] == [{"description": "Gadget", "qty": "2"}]
    assert r.result("x/0/description").page == 2
    r = run(layer, {**RECORDS, "pages": 1})
    assert r.data["x"] == [{"description": "Widget", "qty": "1"}]


def test_labels_and_proposals_read_only_the_fields_pages():
    layer = drawn([(50, 50, "Total: 10")], [(50, 50, "Total: 20")])
    r = one(layer, {"label": "Total", "type": "integer", "pages": 2})
    assert (r.status, r.value) == ("extracted", 20)
    r = one(drawn([(50, 50, "x")], [(50, 50, "Total: 20")]), {"label": "Total", "pages": 1})
    assert r.status == "missing" and "only on page(s) [2], outside page 1" in r.message
    r = one(
        drawn([(50, 50, "x")], [(50, 50, "77")]),
        {"label": "Missing", "type": "integer", "pages": 1},
        Proposer(77, "77"),
    )
    assert r.status == "unconfirmed" and "on the field's pages" in r.message


GRID = [50, 150, 250, 350]  # column rules


def _grid(top: float, rows: int, row: float = 20.0, merged: dict[int, set[int]] | None = None):
    """Rules for a table of `rows` rows under GRID; `merged` leaves out vertical rules by row."""
    out = [(GRID[0], top + r * row, GRID[-1], top + r * row) for r in range(rows + 1)]
    for r in range(rows):
        for i, x in enumerate(GRID):
            if i not in (merged or {}).get(r, set()):
                out.append((x, top + r * row, x, top + (r + 1) * row))
    return out


def _cells(top: float, rows: Sequence[tuple[str, ...]], row: float = 20.0):
    return [
        (GRID[c] + 4, top + r * row + 14, text)
        for r, values in enumerate(rows)
        for c, text in enumerate(values)
        if text
    ]


def test_cell_numbers_count_tables_on_the_fields_pages():
    first = _cells(100, [("Site", "Count", "Notes"), ("North", "12", "dry")])
    second = _cells(100, [("Site", "Count", "Notes"), ("North", "30", "wet")])
    layer = drawn(first, second, rules={1: _grid(100, 2), 2: _grid(100, 2)})
    assert [t.id for t in layer.tables] == ["p1t0", "p2t0"]
    body = {"cell": {"table": 1, "row": "North", "column": "Count"}, "type": "integer"}
    assert one(layer, body).value == 12
    assert one(layer, {**body, "pages": 2}).value == 30


# --- records across page breaks -----------------------------------------------------------------

LEDGER_SPEC = {"records": {"header": {"item": "Item", "qty": "Qty"}, "stop": ["Total"]},
               "columns": {"qty": "integer"}}  # fmt: skip


@pytest.fixture(scope="module")
def ledger():
    return read(LEDGER.read_bytes())


def test_a_ruled_table_is_followed_over_pages(ledger):
    ex = run(ledger, LEDGER_SPEC)
    rows = ex.data["x"]
    assert len(rows) == 86
    assert rows[0] == {"item": "SK-100", "qty": 10} and rows[-1] == {"item": "SK-185", "qty": 10}
    assert [r["item"] for r in rows] == sorted(r["item"] for r in rows)  # no header, no c/f line
    head = ex.result("x")
    assert "pages 1, 2, 3" in head.message
    assert "'Carried forward' on page 1" in head.message
    assert "'Brought forward' on page 3" in head.message
    pages = [ex.result(f"x/{i}/item").page for i in (0, 39, 40, 79, 80, 85)]
    assert pages == [1, 1, 2, 2, 3, 3]


def test_a_table_cut_off_by_the_fields_pages_is_incomplete(ledger):
    head = one(ledger, {**LEDGER_SPEC, "pages": "1-2"})
    assert head.status == "incomplete" and head.value is None
    assert "80 rows" in head.message and "carries it forward to page 3" in head.message
    ex = run(ledger, {**LEDGER_SPEC, "pages": "2-3"})
    assert len(ex.data["x"]) == 46


def test_borderless_rows_follow_a_repeated_header():
    ex = run(drawn(*TWO_PAGES), RECORDS)
    assert [r["description"] for r in ex.data["x"]] == ["Widget", "Gadget"]
    assert [ex.result(f"x/{i}/qty").page for i in (0, 1)] == [1, 2]


def test_borderless_rows_follow_a_page_that_starts_under_the_same_columns():
    pages = (
        [(50, 50, "Description"), (300, 50, "Qty"), (50, 80, "Widget"), (300, 80, "1")],
        [(50, 50, "Gadget"), (300, 50, "2"), (50, 64, "Sprocket"), (300, 64, "3")],
    )
    ex = run(drawn(*pages), RECORDS)
    assert [r["description"] for r in ex.data["x"]] == ["Widget", "Gadget", "Sprocket"]


def test_rows_whose_next_page_does_not_continue_them_are_incomplete():
    pages = (
        [(50, 50, "Description"), (300, 50, "Qty"), (50, 80, "Widget"), (300, 80, "1")],
        [(120, 50, "A paragraph about something else entirely.")],
    )
    head = one(drawn(*pages), RECORDS)
    assert head.status == "incomplete" and head.value is None
    assert "1 row under the header on page 1" in head.message
    assert "page 2 neither repeats the header" in head.message and "`pages:`" in head.message
    ex = run(drawn(*pages), {**RECORDS, "pages": 1})
    assert ex.data["x"] == [{"description": "Widget", "qty": "1"}]


def test_carried_and_page_furniture_lines_are_left_out():
    pages = (
        [(50, 50, "Description"), (300, 50, "Qty"), (50, 80, "Widget"), (300, 80, "1"),
         (50, 94, "Carried forward"), (300, 94, "1"), (50, 820, "Acme page 1")],
        [(50, 50, "Description"), (300, 50, "Qty"), (50, 64, "Brought forward"), (300, 64, "1"),
         (50, 80, "Gadget"), (300, 80, "2"), (50, 820, "Acme page 2")],
    )  # fmt: skip
    ex = run(drawn(*pages), {**RECORDS, "columns": {"qty": "integer"}})
    assert ex.data["x"] == [
        {"description": "Widget", "qty": 1},
        {"description": "Gadget", "qty": 2},
    ]
    assert "'Carried forward' on page 1" in ex.result("x").message


def test_pages_that_print_the_same_body_are_not_one_table():
    # A stack of one-page forms: the same text at the same heights on every page is a body, not
    # a running head, so the second form's table does not continue the first.
    def form(n):
        return [(50, 50, f"Statement {n}"), (50, 300, "Thank you for your order."),
                (50, 400, "Description"), (300, 400, "Qty"), (50, 430, f"Item {n}"),
                (300, 430, str(n)), (50, 820, f"Page {n}")]  # fmt: skip

    head = one(drawn(form(1), form(2)), RECORDS)
    assert head.status == "incomplete" and head.value is None
    assert "page 2 neither repeats the header" in head.message
    ex = run(drawn(form(1), form(2)), {**RECORDS, "pages": 1})
    assert ex.data["x"] == [{"description": "Item 1", "qty": "1"}]


def test_a_stop_label_ends_only_on_a_word_boundary():
    layer = drawn([(50, 50, "Description"), (300, 50, "Qty"), (50, 80, "Widget"), (300, 80, "1"),
                   (50, 94, "Subtotalizer"), (300, 94, "2"), (50, 108, "Subtotal"), (300, 108, "3")])  # fmt: skip
    ex = run(layer, {"records": {"header": {"d": "Description", "q": "Qty"}, "stop": ["Subtotal"]}})
    assert [r["d"] for r in ex.data["x"]] == ["Widget", "Subtotalizer"]


# --- wrapped rows -------------------------------------------------------------------------------

WRAPPED = [(50, 50, "Description"), (300, 50, "Qty"), (50, 80, "Long widget"), (300, 80, "1"),
           (50, 94, "with attachment"), (50, 120, "Other"), (300, 120, "2")]  # fmt: skip


def test_a_wrapped_line_joins_the_record_above():
    ex = run(drawn(WRAPPED), {**RECORDS, "columns": {"qty": "integer"}})
    assert ex.data["x"] == [
        {"description": "Long widget with attachment", "qty": 1},
        {"description": "Other", "qty": 2},
    ]
    cell = ex.result("x/0/description")
    assert [a.quote.exact for a in cell.anchors] == ["Long widget", "with attachment"]
    first, second = (a.boxes[0] for a in cell.anchors)
    assert second.y0 > first.y0 + 10  # the wrapped line's box, under the first


EVEN = [(50, 50, "Description"), (300, 50, "Qty"), (50, 80, "Long widget"), (300, 80, "1"),
        (50, 94, "with attachment"), (50, 108, "Other"), (300, 108, "2")]  # fmt: skip


def test_a_line_the_spacing_does_not_settle_is_ambiguous():
    head = one(drawn(EVEN), RECORDS)
    assert head.status == "ambiguous" and head.value is None
    assert "'with attachment' on page 1 prints only description" in head.message
    assert "'Long widget'" in head.message and "`filled:`" in head.message


def test_filled_settles_a_wrapped_line():
    body = {"records": {"header": {"description": "Description", "qty": "Qty"}, "filled": "qty"}}
    ex = run(drawn(EVEN), body)
    assert [r["description"] for r in ex.data["x"]] == ["Long widget with attachment", "Other"]


def test_filled_must_be_a_header_key():
    with pytest.raises(SpecError, match=r"records\.filled 'amount' is not a header key"):
        load_spec({"fields": {"x": {"records": {"header": {"d": "D"}, "filled": "amount"}}}})


# --- percent ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("printed", "kind", "status", "value"),
    [
        ("Rate: 45%", "percent", "extracted", "45"),
        ("Rate: 100 %", "percent", "extracted", "100"),
        ("Rate: 150%", "percent", "invalid", None),
        ("Rate: -2.5%", "percent", "invalid", None),
        ("Rate: 150%", "percent any", "extracted", "150"),
        ("Rate: -2.5%", "percent any", "extracted", "-2.5"),
        ("Rate: +3%", "percent any", "extracted", "3"),
    ],
)
def test_percent_is_a_share_and_percent_any_is_any_change(printed, kind, status, value):
    r = one(drawn([(50, 50, printed)]), {"label": "Rate", "type": kind})
    assert (r.status, r.value) == (status, value)
    if status == "invalid":
        assert "percent any" in r.message


# --- cells, sections and labels in the fixtures ----------------------------------------------


def test_cells_beside_merged_and_empty_cells():
    rows = [("Site", "Spring", "Autumn"), ("North", "12", "14"), ("South", "not sampled", ""),
            ("East", "", "9")]  # fmt: skip
    layer = drawn(_cells(100, rows), rules={1: _grid(100, 4, merged={2: {2}})})
    (table,) = layer.tables
    assert (table.rows, table.cols) == (4, 3)

    def cell(row, column):
        return one(layer, {"cell": {"table": 1, "row": row, "column": column}})

    assert cell("South", "Spring").value == "not sampled"
    assert cell("South", "Autumn").value == "not sampled"  # the merged cell spans both
    assert cell(2, 2).value == "not sampled"
    assert cell("East", "Autumn").value == "9"
    empty = cell("East", "Spring")
    assert empty.status == "missing" and "is empty" in empty.message
    assert cell("North", "Autumn").value == "14"


def test_section_printed_twice_under_the_same_parent_is_ambiguous():
    body = [
        (50, y, f"The abutment was inspected from the bank, note {y}.") for y in range(300, 420, 14)
    ]
    layer = drawn(
        [(50, 60, "North abutment", 16), (50, 84, "Findings", 13), (50, 104, "Cracks."),
         (50, 128, "Findings", 13), (50, 148, "Scour."), (50, 180, "South abutment", 16),
         (50, 204, "Findings", 13), (50, 224, "Sound."), (50, 260, "Notes", 16), *body]
    )  # fmt: skip
    r = one(layer, {"section": "Findings", "under": "North abutment"})
    assert r.status == "ambiguous"
    assert "more than once under 'North abutment'" in r.message and "`under:` cannot" in r.message
    r = one(layer, {"section": "Findings", "under": "South abutment"})
    assert (r.status, r.value) == ("extracted", "Sound.")
    r = one(layer, {"section": "Findings"})
    assert r.status == "ambiguous" and "more than once" in r.message


def test_purchase_order_cells_find_the_real_header():
    order = read(ORDER.read_bytes())
    r = one(order, {"cell": {"table": 1, "row": "CB-005", "column": "Qty"}, "type": "integer"})
    assert r.value == 10
    r = one(order, {"cell": {"table": 1, "row": 2, "column": "Qty"}, "type": "integer"})
    assert r.value == 2
    r = one(order, {"label": "Cable box", "column": "Qty", "type": "integer"})
    assert r.value == 10


def test_survey_label_with_a_comma_and_parentheses():
    report = read(REPORT.read_bytes())
    r = one(report, {"label": "Taxa per sample, mean (SD)", "type": "mean_sd"})
    assert (r.status, r.value) == ("extracted", {"mean": "14.2", "sd": "3.1"})
    assert r.anchors[0].quote.exact == "14.2 (3.1)"
