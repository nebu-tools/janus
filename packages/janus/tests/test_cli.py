import json

from janus_pdf.cli import main
from support import INSPECTION, INVOICE

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


def test_bad_input_exits_2(tmp_path, capsys):
    spec = tmp_path / "bad.yaml"
    spec.write_text("fields: {x: {label: X, colum: Y}}\n")
    assert main(["extract", str(spec), str(INVOICE)]) == 2
    assert main(["inspect", str(tmp_path / "nothing.pdf")]) == 2
    err = capsys.readouterr().err
    assert "unknown key(s) colum" in err


def test_inspect_shows_headings_tables_and_where_a_phrase_is(capsys):
    assert main(["inspect", str(INSPECTION), "--find", "Findings"]) == 0
    out = capsys.readouterr().out
    assert "r2: Deck joint | Not reachable | n/a" in out
    assert out.count("10.5 pt bold  Findings") == 2
    assert "label ok  Findings" in out
