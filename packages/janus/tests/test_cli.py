import json

import pytest

from janus_pdf.cli import main
from support import INSPECTION, INVOICE, PACKING

SPEC = """
name: Supplier invoice
fields:
  number: {label: "Invoice No."}
  total: {label: Total due, type: money GBP}
"""


def test_extract_prints_each_field_and_exits_0_when_all_are_extracted(tmp_path, capsys):
    spec = tmp_path / "invoice.yaml"
    spec.write_text(SPEC)
    assert main(["extract", str(spec), str(INVOICE)]) == 0
    out = capsys.readouterr().out
    assert "extracted   total" in out and out.rstrip().endswith("2 extracted")


def test_extract_exits_1_when_a_field_is_not_extracted(tmp_path, capsys):
    spec = tmp_path / "invoice.yaml"
    spec.write_text(SPEC + "  po: {label: PO number}\n")
    assert main(["--json", "extract", str(spec), str(INVOICE)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["data"]["po"] is None
    assert result["data"]["total"] == {"amount": "627.00", "currency": "GBP"}


def test_compare_exits_by_whether_every_check_matched(tmp_path, capsys):
    spec = tmp_path / "invoice.yaml"
    spec.write_text(SPEC)
    good, bad = tmp_path / "good.json", tmp_path / "bad.yaml"
    good.write_text(json.dumps({"total": {"amount": "627.00"}}))
    bad.write_text("number: 2026-0452\n")
    assert main(["compare", str(spec), str(INVOICE), str(good)]) == 0
    assert main(["compare", str(spec), str(INVOICE), str(bad)]) == 1
    assert "mismatch" in capsys.readouterr().out


def test_no_line_of_text_output_ends_in_a_space(tmp_path, capsys):
    spec = tmp_path / "invoice.yaml"
    spec.write_text(SPEC + "  po: {label: PO number}\n")
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps({"number": "INV-1", "total": {"currency": "GBP"}}))
    main(["extract", str(spec), str(INVOICE)])
    main(["compare", str(spec), str(INVOICE), str(reference)])
    main(["inspect", str(INSPECTION), "--find", "Findings"])
    out = capsys.readouterr().out
    assert "match " in out and "missing" in out
    assert [line for line in out.splitlines() if line != line.rstrip()] == []


def test_bad_input_exits_2(tmp_path, capsys):
    spec = tmp_path / "bad.yaml"
    spec.write_text("fields: {x: {label: X, colum: Y}}\n")
    assert main(["extract", str(spec), str(INVOICE)]) == 2
    assert main(["inspect", str(tmp_path / "nothing.pdf")]) == 2
    err = capsys.readouterr().err
    assert "unknown key colum" in err


def test_inspect_shows_headings_tables_and_where_a_phrase_is(capsys):
    assert main(["inspect", str(INSPECTION), "--find", "Findings"]) == 0
    out = capsys.readouterr().out
    assert "r2: Deck joint | Not reachable | n/a" in out
    assert out.count("10.5 pt bold  Findings") == 2
    assert "label ok  Findings" in out


def _fails_plainly(capsys, argv, code, says):
    assert main(argv) == code
    err = capsys.readouterr().err
    assert err.startswith("janus: ") and "Traceback" not in err and says in err, err


def test_a_bad_spec_or_pdf_is_reported_on_one_line_and_exits_2(tmp_path, capsys):
    spec = tmp_path / "invoice.yaml"
    spec.write_text(SPEC)
    empty = tmp_path / "empty.yaml"
    empty.write_text('fields: {x: {label: ":"}}\n')
    _fails_plainly(capsys, ["extract", str(empty), str(INVOICE)], 2, 'x: label: ":" is empty')
    lines = tmp_path / "lines.yaml"
    lines.write_text("fields: {x: {records: {header: {a: Item}, continues: never}}}\n")
    _fails_plainly(capsys, ["extract", str(lines), str(PACKING)], 2, "records.continues")
    broken = tmp_path / "broken.yaml"
    broken.write_text("fields: [\n")
    _fails_plainly(capsys, ["extract", str(broken), str(INVOICE)], 2, "not YAML or JSON")
    text = tmp_path / "notes.pdf"
    text.write_text("not a PDF at all")
    _fails_plainly(capsys, ["extract", str(spec), str(text)], 2, "janus: ")
    cut = tmp_path / "cut.pdf"
    cut.write_bytes(INVOICE.read_bytes()[:2000])
    _fails_plainly(capsys, ["inspect", str(cut)], 2, "janus: ")


@pytest.mark.parametrize(
    ("reference", "rules", "says"),
    [
        ("number: [", None, "expected.yaml:"),
        ("- 1\n- 2\n", None, "the reference is a mapping"),
        ("total: {amount: '627.00'}\n", "'*': {tolerance: lots}\n", "tolerance: expected a number"),
        (
            "total: {amount: '627.00'}\n",
            "'*': {casefold: 'no'}\n",
            "casefold: expected true or false",
        ),
        ("total: {amount: '627.00'}\n", "- 1\n", "rules map path patterns"),
        ("total: {amount: '627.00'}\n", "'*': 5\n", "a rule is a mapping"),
    ],
)
def test_bad_reference_or_rules_exit_2(tmp_path, capsys, reference, rules, says):
    spec = tmp_path / "invoice.yaml"
    spec.write_text(SPEC)
    expected = tmp_path / "expected.yaml"
    expected.write_text(reference)
    argv = ["compare", str(spec), str(INVOICE), str(expected)]
    if rules is not None:
        (tmp_path / "rules.yaml").write_text(rules)
        argv += ["--rules", str(tmp_path / "rules.yaml")]
    _fails_plainly(capsys, argv, 2, says)
