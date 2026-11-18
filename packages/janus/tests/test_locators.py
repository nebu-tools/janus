"""The locators on small drawn pages, one case each: what is read, and what is refused."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from janus_pdf import Proposal, SpecError, ValueType, compare, extract, load_spec
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


def test_compare_uses_the_types_equality():
    assert ValueType("text").same("a b", "a  b")
    ex = run(drawn([(50, 50, "a b")]), {"region": {"page": 1, "box": [0, 0, 500, 500]}})
    (check,) = compare(ex, {"x": "a  b"})
    assert check.status == "match"
    (check,) = compare(ex, {"x": "A B"})
    assert check.status == "mismatch"


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
#
# A table is on one page unless the spec says `continues:`. Without it, another page of the
# field that prints the header again, or opens with rows on the same column edges, makes the
# field incomplete; with `continues: header` the table runs on over each following page that
# opens with its header, and with `continues: rows` over each that opens with rows on its edges.

LEDGER_SPEC = {"records": {"header": {"item": "Item", "qty": "Qty"}, "stop": ["Total"],
                           "skip": ["Carried forward", "Brought forward"], "continues": "rows"},
               "columns": {"qty": "integer"}}  # fmt: skip


def continued(form: str = "header", body: dict | None = None, **records) -> dict:
    """`body` (RECORDS by default) with `continues: form` and the other `records` keys."""
    body = body or RECORDS
    return {**body, "records": {**body["records"], "continues": form, **records}}


@pytest.fixture(scope="module")
def ledger():
    return read(LEDGER.read_bytes())


def test_a_declared_ruled_table_is_followed_over_pages(ledger):
    ex = run(ledger, LEDGER_SPEC)
    rows = ex.data["x"]
    assert len(rows) == 86
    assert rows[0] == {"item": "SK-100", "qty": 10} and rows[-1] == {"item": "SK-185", "qty": 10}
    assert [r["item"] for r in rows] == sorted(r["item"] for r in rows)  # no header, no c/f line
    head = ex.result("x")
    assert "pages 1, 2, 3" in head.message
    assert "left out by `skip:`: 'Carried forward' on pages 1, 2" in head.message
    assert "'Brought forward' on pages 2, 3" in head.message
    assert "left out the header printed again on page 2" in head.message
    pages = [ex.result(f"x/{i}/item").page for i in (0, 39, 40, 79, 80, 85)]
    assert pages == [1, 1, 2, 2, 3, 3]


def test_header_form_ends_where_a_page_does_not_open_with_the_header(ledger):
    # The ledger's last page goes on without its header: the strict form ends before it.
    ex = run(ledger, continued("header", LEDGER_SPEC))
    assert len(ex.data["x"]) == 80
    assert ex.result("x").message.startswith("80 rows under the header on pages 1, 2")


def test_an_undeclared_table_printed_again_is_incomplete(ledger):
    records = {k: v for k, v in LEDGER_SPEC["records"].items() if k != "continues"}
    head = one(ledger, {**LEDGER_SPEC, "records": records})
    assert head.status == "incomplete" and head.value is None
    assert "printed again on pages 2, 3" in head.message
    assert "`continues: header`" in head.message and "`continues: rows`" in head.message
    assert "`pages: 1`" in head.message


def test_a_table_cut_off_by_the_fields_pages_says_it_may_go_on(ledger):
    ex = run(ledger, {**LEDGER_SPEC, "pages": "1-2"})
    assert len(ex.data["x"]) == 80
    assert "may go on after page 2, outside the field's pages" in ex.result("x").message
    ex = run(ledger, {**LEDGER_SPEC, "pages": "2-3"})
    assert len(ex.data["x"]) == 46


def _form(n: int, statement: bool) -> list:
    return [*([(50, 50, f"Statement {n}")] if statement else []),
            (50, 150, "Description"), (300, 150, "Qty"),
            (50, 175, ["Widget", "Gadget"][n - 1]), (300, 175, str(n))]  # fmt: skip


@pytest.mark.parametrize("statement", [True, False])
def test_two_one_page_forms_are_not_one_table(statement):
    layer = drawn(_form(1, statement), _form(2, statement))
    head = one(layer, RECORDS)
    assert head.status == "incomplete" and head.value is None
    assert "printed again on page 2" in head.message
    assert "`continues: header`" in head.message and "`pages: 1`" in head.message
    ex = run(layer, {**RECORDS, "pages": 1})
    assert ex.data["x"] == [{"description": "Widget", "qty": "1"}]
    for form in ("header", "rows"):
        ex = run(layer, continued(form))
        assert [r["description"] for r in ex.data["x"]] == ["Widget", "Gadget"]
        assert [ex.result(f"x/{i}/qty").page for i in (0, 1)] == [1, 2]
        assert ("'Statement 2' on page 2" in ex.result("x").message) == statement


def test_a_table_printed_again_after_a_blank_page_is_incomplete():
    table = _form(1, False)
    layer = drawn(table, [], table)
    head = one(layer, RECORDS)
    assert head.status == "incomplete" and "printed again on page 3" in head.message
    head = one(layer, continued("rows"))
    assert head.status == "incomplete"
    assert "ends on page 1 because page 2 does not continue it" in head.message
    assert "printed again on page 3" in head.message and "`pages: 1`" in head.message
    ex = run(layer, {**RECORDS, "pages": 1})
    assert ex.data["x"] == [{"description": "Widget", "qty": "1"}]


def test_a_page_of_other_text_does_not_continue_the_table():
    pages = (
        [(50, 50, "Description"), (300, 50, "Qty"), (50, 80, "Widget"), (300, 80, "1")],
        [(120, 50, "A paragraph about something else entirely.")],
    )
    ex = run(drawn(*pages), RECORDS)
    assert ex.data["x"] == [{"description": "Widget", "qty": "1"}]


def test_declared_borderless_rows_run_on_under_the_same_columns():
    pages = (
        [(50, 50, "Description"), (300, 50, "Qty"), (50, 80, "Widget"), (300, 80, "1")],
        [(50, 50, "Gadget"), (300, 50, "2"), (50, 64, "Sprocket"), (300, 64, "3")],
    )
    head = one(drawn(*pages), RECORDS)
    assert head.status == "incomplete" and "printed again on page 2" in head.message
    ex = run(drawn(*pages), continued("rows"))
    assert [r["description"] for r in ex.data["x"]] == ["Widget", "Gadget", "Sprocket"]
    ex = run(drawn(*pages), continued("header"))  # page 2 does not open with the header
    assert [r["description"] for r in ex.data["x"]] == ["Widget"]


def _ledger_page(n: int) -> list:
    head = [(50, 60, "Description"), (300, 60, "Qty")] if n == 1 else []
    rows = [(x, 100 + 14 * i, text) for i in range(3)
            for x, text in ((50, f"Item {n}{i}"), (300, str(i)))]  # fmt: skip
    return [(50, 40, "Acme Ltd stock ledger"), *head, *rows, (50, 820, f"Page {n} of 3")]


def test_running_heads_and_feet_are_left_out_of_a_declared_table_and_reported():
    layer = drawn(*(_ledger_page(n) for n in (1, 2, 3)))
    head = one(layer, RECORDS)
    assert head.status == "incomplete" and "printed again on pages 2, 3" in head.message
    ex = run(layer, continued("rows"))
    rows = ex.data["x"]
    assert [r["description"] for r in rows] == [f"Item {n}{i}" for n in (1, 2, 3) for i in range(3)]
    assert [ex.result(f"x/{i}/qty").page for i in (0, 3, 6)] == [1, 2, 3]
    message = ex.result("x").message
    assert "'Acme Ltd stock ledger' on pages 2, 3" in message
    assert "'Page 2 of 3' on page 2" in message and "'Page 3 of 3' on page 3" in message


CARRIED = (
    [(50, 50, "Description"), (300, 50, "Qty"), (50, 80, "Widget"), (300, 80, "1"),
     (50, 94, "Carried forward"), (300, 94, "1")],
    [(50, 50, "Description"), (300, 50, "Qty"), (50, 64, "Brought forward"), (300, 64, "1"),
     (50, 80, "Gadget"), (300, 80, "2")],
)  # fmt: skip


def test_skip_leaves_out_carried_forward_lines_and_lists_them():
    body = {**RECORDS, "columns": {"qty": "integer"}}
    ex = run(drawn(*CARRIED), continued("header", body))  # the words alone leave out nothing
    assert [r["description"] for r in ex.data["x"]] == [
        "Widget", "Carried forward", "Brought forward", "Gadget"]  # fmt: skip
    ex = run(drawn(*CARRIED), continued("header", body, skip=["Carried", "Brought forward"]))
    assert ex.data["x"] == [
        {"description": "Widget", "qty": 1},
        {"description": "Gadget", "qty": 2},
    ]
    message = ex.result("x").message
    assert "left out by `skip:`: 'Carried forward 1' on page 1" in message
    assert "'Brought forward 1' on page 2" in message


def test_a_row_is_never_left_out_for_its_words():
    layer = drawn([(50, 150, "Description"), (300, 150, "Qty"), (50, 175, "Alpha"), (300, 175, "1"),
                   (50, 189, "Continued education"), (300, 189, "2"),
                   (50, 203, "Beta"), (300, 203, "3")])  # fmt: skip
    ex = run(layer, RECORDS)
    assert [r["description"] for r in ex.data["x"]] == ["Alpha", "Continued education", "Beta"]
    assert ex.result("x").message == "3 rows under the header on page 1"


def test_skip_leaves_out_a_footer_that_fills_every_column():
    def page(n: int, *rows: tuple[str, str]) -> list:
        head = [(50, 60, "Description"), (300, 60, "Qty")] if n == 1 else []
        body = [
            (x, 100 + 14 * i, t)
            for i, row in enumerate(rows)
            for x, t in zip((50, 300), row, strict=True)
        ]
        return [*head, *body, (50, 820, "Footer"), (300, 820, "99")]

    layer = drawn(page(1, ("Alpha", "1")), page(2, ("Beta", "2")))
    ex = run(layer, continued("rows"))
    assert [r["description"] for r in ex.data["x"]] == ["Alpha", "Footer", "Beta", "Footer"]
    ex = run(layer, continued("rows", skip="Footer"))
    assert ex.data["x"] == [
        {"description": "Alpha", "qty": "1"},
        {"description": "Beta", "qty": "2"},
    ]
    assert "left out by `skip:`: 'Footer 99' on pages 1, 2" in ex.result("x").message


def test_stop_and_skip_cannot_name_the_same_row():
    with pytest.raises(SpecError, match=r"records\.stop and records\.skip both name 'total'"):
        load_spec({"fields": {"x": {"records": {"header": {"d": "D"}, "stop": "Total",
                                                "skip": ["total"]}}}})  # fmt: skip


def test_a_stop_label_ends_only_on_a_word_boundary():
    layer = drawn([(50, 50, "Description"), (300, 50, "Qty"), (50, 80, "Widget"), (300, 80, "1"),
                   (50, 94, "Subtotalizer"), (300, 94, "2"), (50, 108, "Subtotal"), (300, 108, "3")])  # fmt: skip
    ex = run(layer, {"records": {"header": {"d": "Description", "q": "Qty"}, "stop": ["Subtotal"]}})
    assert [r["d"] for r in ex.data["x"]] == ["Widget", "Subtotalizer"]


def test_borderless_records_on_a_rotated_page():
    layer = drawn(_form(1, True), rotation=90)
    ex = run(layer, RECORDS)
    assert ex.data["x"] == [{"description": "Widget", "qty": "1"}]


# --- wrapped rows -------------------------------------------------------------------------------
#
# In a table without rules, a line that leaves a column empty may wrap the record above or start
# one. `filled: {first: [...]}` names the columns every record fills on its first line;
# `filled: {last: [...]}` the columns it fills on its last.

WRAPPED = [(50, 150, "Description"), (300, 150, "Qty"), (50, 175, "Alpha"), (300, 175, "1"),
           (50, 187, "Long beta"), (50, 205, "attachment"), (300, 205, "2"),
           (50, 235, "Gamma"), (300, 235, "3")]  # fmt: skip


def _filled(on: str) -> dict:
    return {"records": {**RECORDS["records"], "filled": {on: ["qty"]}},
            "columns": {"qty": "integer"}}  # fmt: skip


def test_an_undeclared_partial_line_is_ambiguous():
    head = one(drawn(WRAPPED), RECORDS)
    assert head.status == "ambiguous" and head.value is None
    assert "'Long beta' on page 1 prints only description, not qty" in head.message
    assert "`filled: {first: [qty]}`" in head.message


def test_filled_first_starts_a_record_on_each_line_that_fills_it():
    ex = run(drawn(WRAPPED), _filled("first"))
    assert ex.data["x"] == [
        {"description": "Alpha Long beta", "qty": 1},
        {"description": "attachment", "qty": 2},
        {"description": "Gamma", "qty": 3},
    ]
    cell = ex.result("x/0/description")
    assert [a.quote.exact for a in cell.anchors] == ["Alpha", "Long beta"]
    first, second = (a.boxes[0] for a in cell.anchors)
    assert second.y0 > first.y0 + 10  # the wrapped line's box, under the first


def test_filled_last_ends_a_record_on_each_line_that_fills_it():
    ex = run(drawn(WRAPPED), _filled("last"))
    assert [r["description"] for r in ex.data["x"]] == ["Alpha", "Long beta attachment", "Gamma"]


HALVES = [(50, 150, "Description"), (300, 150, "Qty"), (50, 175, "First half"),
          (50, 187, "Second half"), (300, 187, "2"), (50, 215, "Other"), (300, 215, "3")]  # fmt: skip


def test_a_partial_line_before_the_first_record_is_ambiguous():
    head = one(drawn(HALVES), RECORDS)
    assert head.status == "ambiguous" and "'First half' on page 1" in head.message
    head = one(drawn(HALVES), _filled("first"))
    assert head.status == "ambiguous"
    assert "before the first line that fills qty, so it belongs to no record" in head.message
    assert "`filled:`" in head.message and "`skip:`" in head.message
    ex = run(drawn(HALVES), _filled("last"))
    assert [r["description"] for r in ex.data["x"]] == ["First half Second half", "Other"]


def test_a_partial_line_atop_a_continued_page_joins_the_last_record():
    pages = (
        [(50, 50, "Description"), (300, 50, "Qty"), (50, 80, "Widget"), (300, 80, "1")],
        [(50, 50, "Description"), (300, 50, "Qty"), (50, 80, "with a bracket"),
         (50, 94, "Gadget"), (300, 94, "2")],
    )  # fmt: skip
    body = _filled("first")
    head = one(drawn(*pages), body)
    assert head.status == "incomplete"
    for form in ("header", "rows"):
        ex = run(drawn(*pages), continued(form, body))
        assert [r["description"] for r in ex.data["x"]] == ["Widget with a bracket", "Gadget"]
        assert ex.result("x/0/description").anchors[1].boxes[0].page == 2


def test_filled_must_be_a_header_key():
    with pytest.raises(SpecError, match=r"records\.filled\.first 'amount' is not a header key"):
        load_spec({"fields": {"x": {"records": {"header": {"d": "D"},
                                                "filled": {"first": "amount"}}}}})  # fmt: skip
    with pytest.raises(SpecError, match=r"records\.filled takes one of first or last"):
        load_spec({"fields": {"x": {"records": {"header": {"d": "D"},
                                                "filled": {"first": "d", "last": "d"}}}}})  # fmt: skip


# --- sections and pages -------------------------------------------------------------------------

FINDINGS = "The deck shows hairline cracks along the north edge."
MORE = "The bearings were seized and need replacing soon."


def test_a_section_stays_on_the_fields_pages():
    layer = drawn([(50, 60, "Findings", 16), (50, 84, FINDINGS)], [(50, 60, MORE)])
    r = one(layer, {"section": "Findings", "pages": 1})
    assert (r.status, r.value) == ("extracted", FINDINGS)
    assert "may go on after page 1, outside the field's pages" in r.message
    assert one(layer, {"section": "Findings"}).value == f"{FINDINGS} {MORE}"


def test_a_section_over_a_page_break_leaves_out_running_heads_and_reports_them():
    def page(n, *body):
        return [(50, 40, "Bridge inspection report"), *body, (50, 820, f"Page {n} of 2")]

    layer = drawn(
        page(1, (50, 120, "Findings", 16), (50, 144, FINDINGS)),
        page(2, (50, 120, MORE), (50, 200, "Notes", 16), (50, 224, "None.")),
    )
    r = one(layer, {"section": "Findings"})
    assert (r.status, r.value) == ("extracted", f"{FINDINGS} {MORE}")
    assert "'Page 1 of 2' on page 1" in r.message
    assert "'Bridge inspection report' on page 2" in r.message
    alone = drawn(page(1, (50, 120, "Findings", 16), (50, 144, FINDINGS),
                       (50, 200, "Notes", 16), (50, 224, "None.")), page(2))  # fmt: skip
    assert one(alone, {"section": "Findings"}).message == ""  # ordinary text on one page


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


# In a table without rules, vertical spacing and the wording of a row decide nothing: the table
# runs while lines fit its columns. What ends it, or marks a line as another table's, is column
# alignment, the header's own text and set, the columns' types and the keys the spec declares.

B = True  # a bold item: (x, y, text, size, B)


def test_a_gap_between_rows_does_not_end_the_table():
    gap = [(50, 150, "Description"), (300, 150, "Qty"), (50, 175, "Alpha"), (300, 175, "1"),
           (50, 189, "Beta"), (300, 189, "2"), (50, 260, "Gamma"), (300, 260, "3")]  # fmt: skip
    ex = run(drawn(gap), RECORDS)
    assert [r["description"] for r in ex.data["x"]] == ["Alpha", "Beta", "Gamma"]
    wrapped = [*gap[:6], (50, 260, "with a long tail"), (50, 300, "Gamma"), (300, 300, "3")]
    ex = run(drawn(wrapped), _filled("first"))
    assert ex.data["x"] == [
        {"description": "Alpha", "qty": 1},
        {"description": "Beta with a long tail", "qty": 2},
        {"description": "Gamma", "qty": 3},
    ]


def _product_pages(header_bold: bool) -> tuple[list, list]:
    """Page 1 holds the Description | Qty table; page 2 opens with another table, Product |
    Price, on the same column edges."""
    style = (11, header_bold)
    one_ = [
        (50, 60, "Description", *style),
        (300, 60, "Qty", *style),
        (50, 90, "Widget"),
        (300, 90, "1"),
        (50, 104, "Gadget"),
        (300, 104, "2"),
    ]
    two = [(50, 60, "Product", *style), (300, 60, "Price", *style),
           (50, 90, "Lamp"), (300, 90, "12"), (50, 104, "Desk"), (300, 104, "80")]  # fmt: skip
    return one_, two


def test_header_form_ends_at_a_page_that_opens_with_another_header():
    ex = run(drawn(*_product_pages(header_bold=False)), continued("header"))
    assert ex.result("x").status == "extracted"
    assert [r["description"] for r in ex.data["x"]] == ["Widget", "Gadget"]
    assert ex.result("x").message == "2 rows under the header on page 1"


def test_rows_form_sees_another_header_set_like_its_own():
    head = one(drawn(*_product_pages(header_bold=True)), continued("rows"))
    assert head.status == "incomplete" and head.value is None
    assert "the line 'Product Price' on page 2 is set like the header" in head.message
    assert "`stop:`" in head.message and "`pages:`" in head.message


def test_rows_form_sees_another_header_that_fails_a_columns_type():
    body = {**RECORDS, "columns": {"qty": "integer"}}
    head = one(drawn(*_product_pages(header_bold=False)), continued("rows", body))
    assert head.status == "invalid" and head.value is None
    assert "qty 'Price' in the row 'Product Price' on page 2" in head.message
    assert "`stop:`" in head.message and "`skip:`" in head.message and "`pages:`" in head.message


def test_rows_form_cannot_tell_another_header_set_like_the_rows():
    # The documented limit: header and body set alike, columns untyped. The page gives no
    # evidence, so `continues: rows` reads the other header as a record.
    ex = run(drawn(*_product_pages(header_bold=False)), continued("rows"))
    assert ex.result("x").status == "extracted"
    rows = [r["description"] for r in ex.data["x"]]
    assert rows == ["Widget", "Gadget", "Product", "Lamp", "Desk"]
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    assert "set like the body and the columns are untyped text" in readme


def test_rows_form_leaves_out_the_header_printed_again():
    pages = (
        [(50, 60, "Description"), (300, 60, "Qty"), (50, 90, "Widget"), (300, 90, "1")],
        [(50, 60, "Description"), (300, 60, "Qty"), (50, 90, "Gadget"), (300, 90, "2")],
    )  # fmt: skip
    ex = run(drawn(*pages), continued("rows"))
    assert [r["description"] for r in ex.data["x"]] == ["Widget", "Gadget"]
    assert "left out the header printed again on page 2" in ex.result("x").message


def test_a_title_over_the_continued_table_is_incomplete_until_skip_names_it():
    pages = (
        [(50, 60, "Description"), (300, 60, "Qty"), (50, 90, "Widget"), (300, 90, "1")],
        [(50, 40, "Table 3 (continued)"), (50, 60, "Description"), (300, 60, "Qty"),
         (50, 90, "Gadget"), (300, 90, "2")],
    )  # fmt: skip
    for form in ("header", "rows"):
        head = one(drawn(*pages), continued(form))
        assert head.status == "incomplete" and head.value is None
        assert "under the line 'Table 3 (continued)'" in head.message
        assert "`skip:`" in head.message and "`pages: 1`" in head.message
        ex = run(drawn(*pages), continued(form, skip="Table 3"))
        assert [r["description"] for r in ex.data["x"]] == ["Widget", "Gadget"]
        assert "left out by `skip:`: 'Table 3 (continued)' on page 2" in ex.result("x").message


def test_a_second_table_further_down_the_page_is_seen_by_its_header():
    page = [(50, 60, "Description", 11, B), (300, 60, "Qty", 11, B),
            (50, 90, "Widget"), (300, 90, "1"), (50, 104, "Gadget"), (300, 104, "2"),
            (50, 300, "Product", 11, B), (300, 300, "Price", 11, B),
            (50, 330, "Lamp"), (300, 330, "12")]  # fmt: skip
    head = one(drawn(page), RECORDS)
    assert head.status == "incomplete" and head.value is None
    assert "the line 'Product Price' on page 1 is set like the header (bold" in head.message
    ex = run(drawn(page), {"records": {**RECORDS["records"], "stop": "Product"}})
    assert [r["description"] for r in ex.data["x"]] == ["Widget", "Gadget"]
