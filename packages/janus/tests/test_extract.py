import pytest

import janus_pdf
from janus_pdf import Proposal, SpecError, compare, extract, load_spec
from janus_pdf._index import Index
from support import INVOICE


def run(layer, fields, proposer=None):
    return extract(layer, load_spec({"fields": fields}), proposer)


# --- labels -------------------------------------------------------------------------------------


def test_labels_dates_and_money(invoice):
    ex = run(
        invoice,
        {
            "number": {"label": "Invoice No."},  # set off by a column gap
            "date": {"label": "Date", "type": "date"},
            "customer": {"label": "Customer"},  # set off by a colon
            "due": {"label": "Due", "type": "date DD/MM/YYYY"},
            "total": {"label": "Total due", "type": "money GBP"},
        },
    )
    assert ex.data == {
        "number": "2026-0451",
        "date": "2026-03-12",
        "customer": "Blue Fern Studio",
        "due": "2026-04-11",
        "total": {"amount": "627.00", "currency": "GBP"},
    }
    total = ex.result("total")
    assert total.method == "label"
    assert total.anchor.quote.exact == "£627.00"
    assert total.anchor.boxes and total.anchor.boxes[0].page == 1


def test_a_numeric_date_without_a_format_is_invalid(invoice):
    r = run(invoice, {"due": {"label": "Due", "type": "date"}}).result("due")
    assert r.status == "invalid" and r.value is None
    assert "declare its format" in r.message


@pytest.mark.parametrize(
    ("label", "suggested"),
    [
        ("Total", "'Total due: £627.00' on page 1 (nothing sets it off)"),  # the label is longer
        ("Costumer", "'Customer: Blue Fern Studio' on page 1 (similarity"),  # a typo
    ],
)
def test_near_miss_labels_give_suggestions_not_values(invoice, label, suggested):
    r = run(invoice, {"f": {"label": label}}).result("f")
    assert r.status == "missing" and r.value is None
    assert any(s.startswith(suggested) for s in r.suggestions), r.suggestions


def test_a_short_label_on_a_typed_field_does_not_read_the_rest_of_the_line(order):
    ex = run(
        order,
        {"due": {"label": "Due", "type": "date"}, "on": {"label": "Due date", "type": "date"}},
    )
    assert ex.result("due").status == "invalid" and ex.data["due"] is None
    assert ex.data["on"] == "2026-04-11"


def test_a_label_that_only_begins_a_longer_cell_is_offered_not_read(report):
    r = run(report, {"length": {"label": "Length, mm", "type": "mean_sd"}}).result("length")
    assert r.status == "missing"
    assert r.suggestions == ("'Length, mm, mean ± SD' on page 3 (longer cell)",)


def test_a_label_in_a_table_reads_its_row_under_a_column(report):
    ex = run(
        report,
        {
            "ept": {"label": "EPT individuals, n (%)", "column": "Pool", "type": "count_percent"},
            "length": {"label": "Length, mm, mean ± SD", "column": "Riffle", "type": "mean_sd"},
        },
    )
    # "Pool" is printed under both sites, so the two cells disagree.
    ept = ex.result("ept")
    assert ept.status == "ambiguous" and len(ept.candidates) == 2
    assert [c.value for c in ept.candidates] == [
        {"count": 298, "percent": "27.1"},
        {"count": 201, "percent": "19.8"},
    ]
    assert ex.result("length").status == "ambiguous"


def test_pages_limit_where_a_label_is_looked_for(inspection):
    fields = {"date": {"label": "Inspection date", "type": "date", "pages": "2-3"}}
    r = run(inspection, fields).result("date")
    assert r.status == "missing" and r.suggestions == ()
    assert r.message == "'Inspection date' begins a line only on page(s) [1], outside pages 2-3"
    fields = {"date": {"label": "Inspection date", "type": "date", "pages": 1}}
    assert run(inspection, fields).data["date"] == "2026-03-02"


# --- cell, section, region ----------------------------------------------------------------------


def test_cells_by_position_and_by_row_label_and_header(order, report, inspection):
    assert run(order, {"c": {"cell": {"table": "p1t0", "row": 3, "column": 4}}}).data == {
        "c": "1.085,50 €"
    }
    rating = {"cell": {"table": 1, "row": "Bearings", "column": "Rating"}, "type": "integer"}
    assert run(inspection, {"r": rating}).data == {"r": 3}
    # "Riffle" is under both sites; both cells print 40, so the value stands.
    r = run(report, {"n": {"cell": {"table": 1, "row": "Samples, n", "column": "Riffle"}}}).result(
        "n"
    )
    assert r.status == "extracted" and r.value == "40" and len(r.candidates) == 2
    r = run(report, {"x": {"cell": {"table": 9, "row": 0, "column": 0}}}).result("x")
    assert r.status == "missing" and r.message == "no table 9; the layer has 3"


def test_a_repeated_heading_is_ambiguous_until_under_names_its_parent(inspection):
    r = run(inspection, {"f": {"section": "Findings"}}).result("f")
    assert r.status == "ambiguous"
    assert r.message.endswith("say which with `under:` 'North abutment' or 'South abutment'")
    fields = {"f": {"section": "Findings", "under": "South abutment"}}
    assert run(inspection, fields).data["f"].startswith("Scour below the toe")


def test_a_region_reads_the_words_inside_a_box(invoice):
    fields = {"r": {"region": {"page": 1, "box": [56, 170, 300, 190]}}}
    assert run(invoice, fields).data == {"r": "Customer: Blue Fern Studio Due: 11/04/2026"}


def test_a_not_reported_mark_is_extracted_as_none_and_says_so(inspection):
    fields = {"deck": {"label": "Deck joint", "column": "Rating", "type": "integer"}}
    r = run(inspection, fields).result("deck")
    assert (r.status, r.value, r.printed, r.message) == (
        "extracted",
        None,
        "n/a",
        "printed as 'n/a'",
    )


# --- records ------------------------------------------------------------------------------------


def test_records_under_a_header_that_is_not_the_first_row(order):
    fields = {
        "items": {
            "records": {"header": {"code": "Code", "qty": "Qty", "amount": "Amount"}},
            "columns": {"qty": "integer", "amount": "money EUR 1.234,56"},
        }
    }
    ex = run(order, fields)
    items = ex.data["items"]
    assert [i["code"] for i in items] == ["TR-220", "TR-118", "CB-005", "SV-CAL"]
    assert items[1] == {
        "code": "TR-118",
        "qty": 1,
        "amount": {"amount": "1085.50", "currency": "EUR"},
    }
    assert ex.result("items").method == "records"
    assert ex.result("items/1/amount").anchor.cells[0].row == 3


def test_records_without_rules_stop_at_a_stop_label(invoice):
    header = {"description": "Description", "qty": "Qty", "amount": "Amount"}
    fields = {
        "lines": {
            "records": {"header": header, "stop": ["Subtotal"]},
            "columns": {"qty": "integer", "amount": "money GBP"},
        }
    }
    ex = run(invoice, fields)
    lines = ex.data["lines"]
    assert ex.result("lines").method == "records:layout"
    assert [line["amount"]["amount"] for line in lines] == ["150.00", "140.00", "55.50", "177.00"]
    assert lines[0] == {
        "description": "Steel widget, 40 mm",
        "qty": 120,
        "amount": {"amount": "150.00", "currency": "GBP"},
    }


def test_records_keep_a_not_reported_cell_as_none(inspection):
    fields = {
        "ratings": {
            "records": {"header": {"element": "Element", "rating": "Rating"}},
            "columns": {"rating": "integer"},
        }
    }
    ex = run(inspection, fields)
    assert [r["rating"] for r in ex.data["ratings"]] == [3, None, 1]
    assert ex.result("ratings").message == "3 rows under the header on page 1"


def test_records_with_a_header_nowhere_are_missing(invoice):
    fields = {"x": {"records": {"header": {"a": "Part number", "b": "Qty"}}}}
    r = run(invoice, fields).result("x")
    assert r.status == "missing" and "Part number, Qty" in r.message


# --- proposals ----------------------------------------------------------------------------------


class Answers:
    name = "answers"

    def __init__(self, **answers):
        self.answers = answers
        self.asked = []

    def propose(self, layer, field, result):  # noqa: ARG002 - the proposer protocol
        self.asked.append(field.path)
        return self.answers.get(field.path)


def test_proposals_are_confirmed_or_marked_unconfirmed(invoice):
    answers = Answers(
        vat=Proposal({"amount": "104.50", "currency": "GBP"}, "£104.50"),
        po=Proposal("PO-1182", "PO-1182"),  # not printed
        due=Proposal("2026-04-11", "11/04/2026"),  # printed, but the type cannot read it
        customer=Proposal("Blue Fern Studios", "Blue Fern Studio"),  # reads as something else
    )
    fields = {
        "vat": {"label": "Tax", "type": "money GBP"},
        "po": {"label": "PO number"},
        "due": {"label": "Due", "type": "date"},
        "customer": {"label": "Client"},
    }
    ex = run(invoice, fields, answers)
    vat = ex.result("vat")
    assert vat.status == "extracted" and vat.method == "proposed:answers"
    assert vat.anchor.quote.exact == "£104.50"
    assert vat.message == "confirmed by its quote on page 1"
    for path in ("po", "due", "customer"):
        r = ex.result(path)
        assert r.status == "unconfirmed" and r.value is None, path
        assert ex.data[path] is None
    assert ex.result("po").message.startswith("the quote is not printed in the document")


def test_a_proposer_is_not_asked_about_extracted_fields(invoice):
    answers = Answers()
    run(invoice, {"total": {"label": "Total due"}, "vat": {"label": "Tax"}}, answers)
    assert answers.asked == ["vat"]


# --- compare ------------------------------------------------------------------------------------


def test_compare(invoice, inspection):
    fields = {
        "total": {"label": "Total due", "type": "money GBP"},
        "number": {"label": "Invoice No."},
        "vat": {"label": "Tax", "type": "money GBP"},
    }
    reference = {
        "total": {"amount": 627, "currency": "GBP"},
        "number": "2026-451",
        "vat": {"amount": "104.50"},
        "po": "PO-1182",
    }
    checks = {c.path: c for c in compare(run(invoice, fields), reference)}
    assert checks["total/amount"].status == "match"
    assert checks["total/currency"].status == "match"
    assert checks["number"].status == "mismatch"  # text, not a number
    assert (checks["vat/amount"].status, checks["vat/amount"].message) == (
        "not_extracted",
        "the field is missing",
    )
    assert checks["po"].message == "the path is not in the spec"

    rules = {"total/amount": {"tolerance": "0.5"}}
    near = compare(run(invoice, fields), {"total": {"amount": "627.40"}}, rules)
    assert near[0].status == "match"

    deck = {"deck": {"label": "Deck joint", "column": "Rating", "type": "integer"}}
    (check,) = compare(run(inspection, deck), {"deck": 2})
    assert check.status == "not_extracted"
    assert check.message == "printed as 'n/a', which marks the value as not reported"


# --- specs and the index ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "error"),
    [
        ({"x": {"label": "X", "colum": "Y"}}, "unknown key"),
        ({"x": {"label": "X", "section": "Y"}}, "exactly one"),
        ({"x": {"cell": {"table": 1, "row": 0}}}, "cell needs column"),
        ({"x": {"section": "Y", "type": "integer"}}, "a section is text"),
        ({"x": {"label": "X", "under": "Y"}}, "`under` goes with `section`"),
        (
            {"x": {"records": {"header": {"a": "A"}}, "columns": {"b": "integer"}}},
            "not in the header",
        ),
        ({"x": {"label": "X", "pages": "two"}}, "pages is a page number"),
        ({"x y": {"label": "X"}}, "field names"),
    ],
)
def test_bad_specs_fail_when_they_load(fields, error):
    with pytest.raises(SpecError, match=error):
        load_spec({"fields": fields})


def test_groups_nest_paths_and_data():
    spec = load_spec({"fields": {"seller": {"fields": {"name": {"label": "From"}}}}})
    assert [f.path for f in spec.fields] == ["seller/name"]
    assert (
        spec.hash == load_spec({"fields": {"seller": {"fields": {"name": {"label": "From"}}}}}).hash
    )


def test_the_index_is_built_once_per_layer(monkeypatch):
    layer = janus_pdf.read(INVOICE)  # a layer no other test has indexed
    built = []
    original = Index.__init__

    def counting(self, layer):
        built.append(layer)
        original(self, layer)

    monkeypatch.setattr(Index, "__init__", counting)
    for _ in range(3):
        run(layer, {"total": {"label": "Total due"}, "missing": {"label": "Nothing like this"}})
    janus_pdf.inspect(layer, find="Total")
    assert len(built) == 1
